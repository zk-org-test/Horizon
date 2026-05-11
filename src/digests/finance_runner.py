"""Finance digest data collection and rendering."""

from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx
from ddgs import DDGS

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from ..models import FinanceDigestConfig
from .summarizers import FinanceDigestSummary, FinanceSummarizer

def _load_yfinance():
    try:
        import yfinance as module
        return module
    except ImportError:
        pass

    repo_root = Path(__file__).resolve().parents[2]
    candidates = sorted((repo_root.parent / "TradingAgents" / ".venv" / "lib").glob("python*/site-packages"))
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.append(candidate_str)
        try:
            import yfinance as module
            return module
        except ImportError:
            continue

    return None


yf = _load_yfinance()


def get_previous_trading_day(current: datetime) -> datetime:
    """Return the most recent weekday before *current*."""
    previous = current - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous.replace(hour=0, minute=0, second=0, microsecond=0)


def pick_strongest_group(movers: list[dict[str, Any]], key: str) -> str:
    """Pick the dominant group by count, then by average change."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for mover in movers:
        name = str(mover.get(key) or "未分类").strip()
        buckets[name].append(float(mover.get("change_pct") or 0.0))

    ranked = sorted(
        buckets.items(),
        key=lambda item: (len(item[1]), sum(item[1]) / len(item[1])),
        reverse=True,
    )
    return ranked[0][0] if ranked else "未分类"


@dataclass
class MarketMover:
    symbol: str
    name: str
    market: str
    change_pct: float
    price: Optional[float] = None
    prev_close: Optional[float] = None
    sector: str = "未分类"
    industry: str = "未分类"
    volume: Optional[int] = None
    source_url: Optional[str] = None
    catalyst: Optional[str] = None
    news_headlines: list[str] | None = None

    def to_line(self) -> str:
        catalyst = f" | 催化：{self.catalyst}" if self.catalyst else ""
        sector = self.sector or "未分类"
        industry = self.industry or "未分类"
        return (
            f"- `{self.symbol}` {self.name} {self.change_pct:+.2f}%"
            f" | {sector} / {industry}{catalyst}"
        )


class FinancialDatasetsClient:
    """Thin async client for free-tier Financial Datasets enrichment."""

    def __init__(self, api_key: Optional[str], http_client: httpx.AsyncClient):
        self.api_key = api_key
        self.client = http_client
        self.base_url = "https://api.financialdatasets.ai"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _get(self, path: str, **params: Any) -> Optional[dict[str, Any]]:
        if not self.api_key:
            return None

        headers = {"X-API-KEY": self.api_key}
        try:
            response = await self.client.get(
                f"{self.base_url}{path}",
                params=params,
                headers=headers,
                timeout=30.0,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        return response.json()

    async def get_company_facts(self, ticker: str) -> dict[str, Any]:
        payload = await self._get("/company/facts", ticker=ticker)
        return (payload or {}).get("company_facts") or {}

    async def get_news(self, ticker: str, limit: int = 5) -> list[dict[str, Any]]:
        payload = await self._get("/news", ticker=ticker, limit=limit)
        return (payload or {}).get("news") or []

    async def get_earnings(self, ticker: str, limit: int = 3) -> list[dict[str, Any]]:
        payload = await self._get("/earnings", ticker=ticker, limit=limit)
        return (payload or {}).get("earnings") or []

    async def get_filings(self, ticker: str, limit: int = 3) -> list[dict[str, Any]]:
        payload = await self._get("/filings", ticker=ticker, limit=limit)
        return (payload or {}).get("filings") or []


class FinanceDigestRunner:
    """Build the finance daily digest."""

    def __init__(
        self,
        config: FinanceDigestConfig,
        ai_client: AIClient,
        http_client: httpx.AsyncClient,
    ):
        self.config = config
        self.ai_client = ai_client
        self.http_client = http_client
        self.financial_client = FinancialDatasetsClient(
            os.getenv(config.financial_datasets_api_key_env),
            http_client,
        )

    async def run(self, now: Optional[datetime] = None) -> dict[str, Any]:
        current = now or datetime.now()
        trade_day = get_previous_trading_day(current)

        us_movers, hk_movers = await asyncio.gather(
            asyncio.to_thread(
                self._fetch_market_movers,
                "us",
                self.config.us_candidate_limit,
                trade_day.date(),
            ),
            asyncio.to_thread(
                self._fetch_market_movers,
                "hk",
                self.config.hk_candidate_limit,
                trade_day.date(),
            ),
        )

        us_top = us_movers[: self.config.top_n]
        hk_top = hk_movers[: self.config.top_n]

        await asyncio.gather(
            *(self._enrich_mover(mover, fetch_public_news=False) for mover in us_top),
            *(self._enrich_mover(mover, fetch_public_news=False) for mover in hk_top),
        )

        all_top = us_top + hk_top
        strongest_sector = pick_strongest_group([asdict(item) for item in all_top], "sector")
        strongest_industry = pick_strongest_group([asdict(item) for item in all_top], "industry")
        leader = self._pick_leader(all_top, strongest_sector)
        ai_insights = await self._generate_ai_insights(trade_day.date(), us_top, hk_top, strongest_sector, strongest_industry)

        confidence_note = ai_insights["confidence_note"]
        if not self.financial_client.enabled:
            confidence_note = (
                confidence_note + " 当前未配置 Financial Datasets API Key，部分美股催化来自公开 Yahoo 数据。"
            ).strip()

        summary = FinanceDigestSummary(
            date=current.strftime("%Y-%m-%d"),
            market_summary=ai_insights["market_summary"],
            us_top_movers=[item.to_line() for item in us_top],
            hk_top_movers=[item.to_line() for item in hk_top],
            strongest_sector=strongest_sector,
            strongest_industry=strongest_industry,
            leader=leader,
            catalysts=ai_insights["catalysts"],
            trend_outlook=ai_insights["trend_outlook"],
            confidence_note=confidence_note,
        )
        markdown = FinanceSummarizer().render(summary)
        return {
            "kind": "finance",
            "title": f"{self.config.webhook_title} | {summary.date}",
            "summary": markdown,
            "date": summary.date,
            "lang": self.config.language,
        }

    def _fetch_market_movers(self, market: str, candidate_limit: int, trade_day: date) -> list[MarketMover]:
        if yf is None:
            raise RuntimeError("yfinance is required for finance digests. Run `uv sync` to install dependencies.")

        if market == "us":
            response = yf.screen("day_gainers", size=candidate_limit)
        else:
            query = yf.EquityQuery(
                "and",
                [
                    yf.EquityQuery("eq", ["region", "hk"]),
                    yf.EquityQuery("eq", ["exchange", "HKG"]),
                    yf.EquityQuery("gte", ["dayvolume", 50000]),
                    yf.EquityQuery("gte", ["intradayprice", 0.5]),
                ],
            )
            response = yf.screen(
                query,
                size=candidate_limit,
                sortField="percentchange",
                sortAsc=False,
            )

        quotes = self._extract_quotes(response)
        quote_map = {
            quote.get("symbol"): quote
            for quote in quotes
            if quote.get("symbol")
            and str(quote.get("quoteType") or "").upper() == "EQUITY"
            and str(quote.get("typeDisp") or "").lower() != "etf"
        }

        movers: list[MarketMover] = []

        for symbol, quote in quote_map.items():
            change_pct = self._extract_float(quote.get("regularMarketChangePercent"))
            if change_pct is None:
                continue
            movers.append(
                MarketMover(
                    symbol=symbol,
                    name=str(
                        quote.get("shortName")
                        or quote.get("longName")
                        or symbol
                    ),
                    market=market,
                    change_pct=change_pct,
                    price=self._extract_float(quote.get("regularMarketPrice")),
                    prev_close=self._extract_float(quote.get("regularMarketPreviousClose")),
                    volume=self._safe_int(quote.get("regularMarketVolume") or quote.get("dayVolume")),
                    source_url=f"https://finance.yahoo.com/quote/{symbol}",
                )
            )

        movers.sort(key=lambda item: item.change_pct, reverse=True)
        return movers

    @staticmethod
    def _extract_quotes(response: Any) -> list[dict[str, Any]]:
        if isinstance(response, dict):
            if isinstance(response.get("quotes"), list):
                return response["quotes"]
            finance = response.get("finance")
            if isinstance(finance, dict):
                results = finance.get("result") or []
                if results and isinstance(results[0], dict):
                    return results[0].get("quotes") or []
        return []

    async def _enrich_mover(self, mover: MarketMover, fetch_public_news: bool = False) -> None:
        if mover.market == "us" and self.financial_client.enabled:
            facts, news, earnings, filings = await asyncio.gather(
                self.financial_client.get_company_facts(mover.symbol),
                self.financial_client.get_news(mover.symbol),
                self.financial_client.get_earnings(mover.symbol),
                self.financial_client.get_filings(mover.symbol),
            )
            mover.name = str(facts.get("name") or mover.name)
            mover.sector = str(facts.get("sector") or facts.get("sic_sector") or mover.sector)
            mover.industry = str(facts.get("industry") or facts.get("sic_industry") or mover.industry)
            headlines = [str(item.get("title")) for item in news if item.get("title")]
            if earnings:
                headlines.insert(0, "近期有财报/业绩披露")
            if filings:
                headlines.append("存在监管/公告文件更新")
            mover.news_headlines = headlines[:3]
            mover.catalyst = self._pick_catalyst(headlines[:3])
            return

        mover.sector = self._infer_sector_from_name(mover.name)
        mover.industry = self._infer_industry_from_name(mover.name, mover.sector)
        if fetch_public_news:
            try:
                headlines = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_public_news_headlines, mover),
                    timeout=8,
                )
            except Exception:
                headlines = []
            mover.news_headlines = headlines[:3]
            mover.catalyst = self._pick_catalyst(headlines[:3])
        else:
            mover.news_headlines = []
            mover.catalyst = None

    @staticmethod
    def _fetch_public_news_headlines(mover: MarketMover) -> list[str]:
        queries = [
            f"{mover.name} stock",
            f"{mover.symbol} stock news",
        ]
        if mover.market == "hk":
            queries.insert(0, f"{mover.name} 港股")

        headlines: list[str] = []
        try:
            with DDGS() as ddgs:
                for query in queries:
                    for item in ddgs.news(query, max_results=3):
                        title = item.get("title")
                        if title and title not in headlines:
                            headlines.append(str(title))
                        if len(headlines) >= 3:
                            return headlines
        except Exception:
            pass
        return headlines

    async def _generate_ai_insights(
        self,
        trade_day: date,
        us_top: list[MarketMover],
        hk_top: list[MarketMover],
        strongest_sector: str,
        strongest_industry: str,
    ) -> dict[str, Any]:
        payload = {
            "trade_day": trade_day.isoformat(),
            "us_top": [asdict(item) for item in us_top[:8]],
            "hk_top": [asdict(item) for item in hk_top[:8]],
            "strongest_sector": strongest_sector,
            "strongest_industry": strongest_industry,
        }
        system = (
            "你是一名金融晨会纪要分析师。请基于给定的涨幅榜、行业分类和新闻催化，"
            "输出严格 JSON，不要输出额外解释。"
        )
        user = (
            "请用中文输出以下 JSON 字段："
            '{"market_summary":"一句话总览","catalysts":["原因1","原因2","原因3"],'
            '"trend_outlook":"后续趋势判断","confidence_note":"如果公开新闻不足，请明确提示"}\n\n'
            f"数据：{payload}"
        )
        try:
            response = await asyncio.wait_for(
                self.ai_client.complete(system=system, user=user, max_tokens=1200),
                timeout=45,
            )
            result = parse_json_response(response)
        except Exception:
            result = None

        fallback = self._fallback_finance_insights(strongest_sector, strongest_industry, us_top, hk_top)
        if not result:
            return fallback

        return {
            "market_summary": str(result.get("market_summary") or fallback["market_summary"]),
            "catalysts": [str(item) for item in result.get("catalysts") or fallback["catalysts"]],
            "trend_outlook": str(result.get("trend_outlook") or fallback["trend_outlook"]),
            "confidence_note": str(result.get("confidence_note") or fallback["confidence_note"]),
        }

    def _fallback_finance_insights(
        self,
        strongest_sector: str,
        strongest_industry: str,
        us_top: list[MarketMover],
        hk_top: list[MarketMover],
    ) -> dict[str, Any]:
        avg_us = self._average_change(us_top[:5])
        avg_hk = self._average_change(hk_top[:5])
        leader = self._pick_leader(us_top + hk_top, strongest_sector)
        catalysts = self._collect_top_catalysts(us_top + hk_top)
        return {
            "market_summary": (
                f"昨日美股强于港股，最集中的方向是 {strongest_sector} / {strongest_industry}。"
                if avg_us >= avg_hk
                else f"昨日港股强于美股，最集中的方向是 {strongest_sector} / {strongest_industry}。"
            ),
            "catalysts": catalysts or ["公开新闻信号有限，主要仍是主题轮动与事件驱动。"],
            "trend_outlook": (
                f"龙头 {leader} 带动的 {strongest_sector} 板块短线仍有延续可能，"
                "但需要观察下一交易日是否有量能跟随。"
            ),
            "confidence_note": "公开新闻信号不足，结论主要基于涨幅榜结构与行业集中度。",
        }

    @staticmethod
    def _pick_leader(movers: list[MarketMover], strongest_sector: str) -> str:
        preferred = [item for item in movers if item.sector == strongest_sector] or movers
        leader = max(preferred, key=lambda item: item.change_pct, default=None)
        if leader is None:
            return "暂无明显龙头"
        return f"{leader.symbol} ({leader.name}, {leader.change_pct:+.2f}%)"

    @staticmethod
    def _collect_top_catalysts(movers: Iterable[MarketMover]) -> list[str]:
        seen: set[str] = set()
        catalysts: list[str] = []
        for mover in movers:
            if not mover.news_headlines:
                continue
            for headline in mover.news_headlines:
                if headline in seen:
                    continue
                seen.add(headline)
                catalysts.append(headline)
                if len(catalysts) == 3:
                    return catalysts
        return catalysts

    @staticmethod
    def _average_change(movers: list[MarketMover]) -> float:
        if not movers:
            return 0.0
        return sum(item.change_pct for item in movers) / len(movers)

    @staticmethod
    def _pick_catalyst(headlines: list[str]) -> Optional[str]:
        for headline in headlines:
            if headline:
                return headline
        return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_float(value: Any) -> Optional[float]:
        if isinstance(value, dict):
            value = value.get("raw")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _infer_sector_from_name(name: str) -> str:
        lowered = name.lower()
        sector_keywords = {
            "Technology": ["tech", "software", "semi", "chip", "cloud", "ai", "internet", "digital"],
            "Healthcare": ["pharma", "bio", "medical", "health", "hospital", "drug"],
            "Financials": ["bank", "financial", "insurance", "capital", "securities", "broker"],
            "Energy": ["energy", "oil", "gas", "solar", "power", "coal"],
            "Materials": ["mining", "metal", "steel", "lithium", "gold", "copper", "cement"],
            "Consumer": ["retail", "food", "beverage", "auto", "motor", "consumer", "travel"],
            "Industrials": ["shipping", "logistics", "air", "aerospace", "industrial", "machinery"],
            "Real Estate": ["property", "real estate", "reit"],
        }
        for sector, hints in sector_keywords.items():
            if any(hint in lowered for hint in hints):
                return sector
        return "未分类"

    @staticmethod
    def _infer_industry_from_name(name: str, sector: str) -> str:
        lowered = name.lower()
        if sector == "Technology":
            if any(keyword in lowered for keyword in ["semi", "chip"]):
                return "Semiconductors"
            if any(keyword in lowered for keyword in ["cloud", "software", "saas"]):
                return "Software"
        if sector == "Healthcare":
            if "bio" in lowered:
                return "Biotech"
            if "medical" in lowered:
                return "Medical Devices"
        if sector == "Financials" and "bank" in lowered:
            return "Banks"
        if sector == "Energy" and "solar" in lowered:
            return "Solar"
        return sector if sector != "未分类" else "未分类"
