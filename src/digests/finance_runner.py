"""Finance digest data collection and rendering."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

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


SECTOR_ZH_MAP = {
    "Technology": "科技",
    "Information Technology": "科技",
    "Semiconductors": "半导体",
    "Software": "软件",
    "Data Infrastructure": "数据基础设施",
    "IT Services": "IT服务",
    "Energy": "能源",
    "Energy Storage": "储能",
    "Healthcare": "医疗健康",
    "Utilities": "公用事业",
    "Financials": "金融",
    "Capital Markets": "资本市场",
    "Consumer": "消费",
    "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "必选消费",
    "Industrials": "工业",
    "Materials": "材料",
    "Real Estate": "房地产",
    "Communication Services": "通信服务",
    "Network Equipment": "网络设备",
    "Internet Content & Information": "互联网平台",
    "Aerospace & Defense": "航空航天",
    "Solar": "光伏",
    "Biotech": "生物科技",
    "Banks": "银行",
    "Hardware": "硬件",
    "Electronics": "电子",
    "Retail": "零售",
    "Restaurants": "餐饮",
    "Automobiles": "汽车",
    "Luxury Goods": "奢侈品",
    "Apparel": "服装",
    "Consumer Electronics": "消费电子",
    "Telecom Services": "电信服务",
    "Internet Services": "互联网服务",
    "Media": "媒体",
    "Computer Hardware": "计算机硬件",
    "Information Technology Services": "信息技术服务",
    "Auto Parts": "汽车零部件",
    "Biotechnology": "生物科技",
    "Communication Equipment": "通信设备",
    "Software - Infrastructure": "基础软件",
    "Engineering & Construction": "工程建设",
    "Metal Fabrication": "金属加工",
    "Paper & Paper Products": "纸业与纸制品",
    "Leisure": "休闲消费",
    "Semiconductors & Semiconductor Equipment": "半导体及设备",
    "Electrical Equipment": "电气设备",
    "Commercial Services & Supplies": "商业服务与用品",
    "Distributors": "分销商",
    "Independent Power and Renewable Electricity Producers": "独立电力与新能源发电",
    "Aerospace & Defense": "航空航天与国防",
    "Utilities - Renewable": "新能源公用事业",
    "Electrical Equipment & Parts": "电气设备与零部件",
    "Software - Application": "应用软件",
    "Rental & Leasing Services": "租赁服务",
    "Electronics & Computer Distribution": "电子与计算机分销",
    "Education & Training Services": "教育培训服务",
    "Advertising Agencies": "广告营销",
    "Semiconductor Equipment & Materials": "半导体设备与材料",
    "Infrastructure Operations": "基建运营",
    "Basic Materials": "基础材料",
}


def get_previous_trading_day(current: datetime) -> datetime:
    """Return the most recent weekday before *current*."""
    previous = current - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous.replace(hour=0, minute=0, second=0, microsecond=0)


def pick_strongest_group(movers: list[dict[str, Any]], key: str) -> str:
    """Pick the dominant group by count, then by average change."""
    ranked = rank_heat_groups(movers, key, top_n=1)
    return ranked[0]["label"] if ranked else "未分类"


def rank_heat_groups(movers: list[dict[str, Any]], key: str, top_n: int = 5) -> list[dict[str, Any]]:
    """Rank groups by count, then average gain, then the top leader."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mover in movers:
        label = str(mover.get(key) or "未分类").strip()
        buckets[label].append(mover)

    ranked: list[dict[str, Any]] = []
    for label, entries in buckets.items():
        sorted_entries = sorted(entries, key=lambda item: float(item.get("change_pct") or 0.0), reverse=True)
        avg_change = sum(float(item.get("change_pct") or 0.0) for item in entries) / len(entries)
        leader = sorted_entries[0]
        ranked.append(
            {
                "label": label,
                "count": len(entries),
                "avg_change": avg_change,
                "leader_symbol": str(leader.get("symbol") or ""),
                "leader_name": str(leader.get("display_name") or leader.get("name") or ""),
                "leader_change": float(leader.get("change_pct") or 0.0),
            }
        )

    ranked.sort(
        key=lambda item: (item["count"], item["avg_change"], item["leader_change"]),
        reverse=True,
    )
    return ranked[:top_n]


@dataclass
class MarketMover:
    symbol: str
    name: str
    market: str
    change_pct: float
    name_zh: Optional[str] = None
    price: Optional[float] = None
    prev_close: Optional[float] = None
    sector: str = "未分类"
    industry: str = "未分类"
    sector_zh: str = "未分类"
    industry_zh: str = "未分类"
    volume: Optional[int] = None
    source_url: Optional[str] = None
    catalyst: Optional[str] = None
    news_headlines: list[str] | None = None
    company_intro: Optional[str] = None
    main_products: Optional[str] = None
    move_reason: Optional[str] = None
    business_summary: Optional[str] = None
    search_context: list[str] | None = None

    @property
    def display_name(self) -> str:
        if self.name_zh:
            return f"{self.name}（{self.name_zh}）"
        return self.name

    @property
    def linked_symbol(self) -> str:
        if self.source_url:
            return f"[`{self.symbol}`]({self.source_url})"
        return f"`{self.symbol}`"

    def to_brief_line(self, rank: int) -> str:
        category = self.sector_zh or "未分类"
        subcategory = self.industry_zh or "未分类"
        category_text = category if category == subcategory else f"{category} / {subcategory}"
        short_reason = (self.move_reason or self.catalyst or "").strip()
        catalyst = f" | 触发：{short_reason[:72]}" if short_reason else ""
        return (
            f"{rank}. {self.linked_symbol} {self.display_name} | {self.change_pct:+.2f}%"
            f" | 分类：{category_text}{catalyst}"
        )

    def to_focus_block(self, rank: int) -> str:
        category = self.sector_zh or "未分类"
        subcategory = self.industry_zh or "未分类"
        category_text = category if category == subcategory else f"{category} / {subcategory}"
        intro = self.company_intro or "公司介绍待补充。"
        products = self.main_products or "主要产品信息待补充。"
        reason = self.move_reason or self.catalyst or "暂未识别到明确催化，更多体现题材与资金偏好。"
        return (
            f"{rank}. {self.linked_symbol} {self.display_name} | {self.change_pct:+.2f}% | 分类：{category_text}\n"
            f"   公司：{intro}\n"
            f"   产品：{products}\n"
            f"   走强原因：{reason}"
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

    async def get_news(self, ticker: str, limit: int = 3) -> list[dict[str, Any]]:
        payload = await self._get("/news", ticker=ticker, limit=limit)
        return (payload or {}).get("news") or []

    async def get_earnings(self, ticker: str, limit: int = 2) -> list[dict[str, Any]]:
        payload = await self._get("/earnings", ticker=ticker, limit=limit)
        return (payload or {}).get("earnings") or []

    async def get_filings(self, ticker: str, limit: int = 2) -> list[dict[str, Any]]:
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
        self.search_semaphore = asyncio.Semaphore(6)
        self.enable_public_search = os.getenv("HORIZON_ENABLE_PUBLIC_SEARCH", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        self.financial_client = FinancialDatasetsClient(
            os.getenv(config.financial_datasets_api_key_env),
            http_client,
        )

    async def run(self, now: Optional[datetime] = None) -> dict[str, Any]:
        current = now or datetime.now()
        trade_day = get_previous_trading_day(current)

        us_movers, hk_movers = await asyncio.gather(
            asyncio.to_thread(self._fetch_market_movers, "us", self.config.us_candidate_limit),
            asyncio.to_thread(self._fetch_market_movers, "hk", self.config.hk_candidate_limit),
        )

        us_top = us_movers[: self.config.top_n]
        hk_top = hk_movers[: self.config.top_n]

        await asyncio.gather(
            *(self._enrich_mover(mover) for mover in us_top),
            *(self._enrich_mover(mover) for mover in hk_top),
        )
        await self._ai_label_movers(us_top + hk_top)
        await self._ai_deepen_focus_movers(us_top[:5] + hk_top[:5])

        all_top = us_top + hk_top
        strongest_sector = pick_strongest_group([asdict(item) for item in all_top], "sector_zh")
        strongest_industry = pick_strongest_group([asdict(item) for item in all_top], "industry_zh")
        leader = self._pick_leader(all_top, strongest_sector)
        overview_points = self._build_overview_points(us_top, hk_top, strongest_sector, leader)
        ai_insights = await self._generate_ai_insights(trade_day.date(), us_top, hk_top, strongest_sector, strongest_industry)
        heat_rankings = self._build_heat_ranking_lines(all_top, ai_insights.get("heat_reasons"))

        confidence_note = ai_insights["confidence_note"]
        if not self.financial_client.enabled:
            confidence_note = (
                confidence_note + " 当前未配置 Financial Datasets API Key，分类与归因更多依赖模型推断。"
            ).strip()

        summary = FinanceDigestSummary(
            date=current.strftime("%Y-%m-%d"),
            market_summary=ai_insights["market_summary"],
            overview_points=overview_points,
            heat_rankings=heat_rankings,
            us_focus_movers=[item.to_focus_block(index) for index, item in enumerate(us_top[:5], start=1)],
            hk_focus_movers=[item.to_focus_block(index) for index, item in enumerate(hk_top[:5], start=1)],
            us_more_movers=[item.to_brief_line(index) for index, item in enumerate(us_top[5:], start=6)],
            hk_more_movers=[item.to_brief_line(index) for index, item in enumerate(hk_top[5:], start=6)],
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

    def _fetch_market_movers(self, market: str, candidate_limit: int) -> list[MarketMover]:
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
            response = yf.screen(query, size=candidate_limit, sortField="percentchange", sortAsc=False)

        quotes = self._extract_quotes(response)
        movers: list[MarketMover] = []
        for quote in quotes:
            if not self._is_supported_equity_quote(quote):
                continue
            change_pct = self._extract_float(quote.get("regularMarketChangePercent"))
            if change_pct is None:
                continue
            movers.append(
                MarketMover(
                    symbol=str(quote.get("symbol")),
                    name=str(quote.get("shortName") or quote.get("longName") or quote.get("symbol")),
                    market=market,
                    change_pct=change_pct,
                    price=self._extract_float(quote.get("regularMarketPrice")),
                    prev_close=self._extract_float(quote.get("regularMarketPreviousClose")),
                    volume=self._safe_int(quote.get("regularMarketVolume") or quote.get("dayVolume")),
                    source_url=f"https://finance.yahoo.com/quote/{quote.get('symbol')}",
                )
            )

        movers.sort(key=lambda item: item.change_pct, reverse=True)
        return movers

    @staticmethod
    def _is_supported_equity_quote(quote: dict[str, Any]) -> bool:
        symbol = str(quote.get("symbol") or "")
        if not symbol:
            return False
        if str(quote.get("quoteType") or "").upper() != "EQUITY":
            return False

        if symbol.endswith(".HK"):
            stem = symbol[:-3]
            if stem.isdigit() and len(stem) > 4:
                return False

        type_disp = str(quote.get("typeDisp") or "").lower()
        if type_disp in {"etf", "fund", "reit", "warrant", "cbbc"}:
            return False

        name_parts = [
            str(quote.get("shortName") or ""),
            str(quote.get("longName") or ""),
            str(quote.get("displayName") or ""),
            symbol,
        ]
        haystack = " ".join(name_parts).lower()
        banned_terms = [
            "认购",
            "认沽",
            "牛熊证",
            "牛證",
            "warrant",
            "callable bull",
            "callable bear",
            "cbbc",
            "inline",
            "rights",
        ]
        if any(term in haystack for term in banned_terms):
            return False

        if symbol.endswith(".HK") and ("@" in haystack or symbol.replace(".HK", "") == (quote.get("shortName") or "")):
            return False

        return True

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

    async def _enrich_mover(self, mover: MarketMover) -> None:
        native_profile_task = asyncio.to_thread(self._fetch_yahoo_profile, mover.symbol)
        native_news_task = asyncio.to_thread(self._fetch_yahoo_news, mover.symbol)

        facts: dict[str, Any] = {}
        fd_news: list[str] = []
        if mover.market == "us" and self.financial_client.enabled:
            facts, news, earnings, filings, profile, yahoo_news = await asyncio.gather(
                self.financial_client.get_company_facts(mover.symbol),
                self.financial_client.get_news(mover.symbol),
                self.financial_client.get_earnings(mover.symbol),
                self.financial_client.get_filings(mover.symbol),
                native_profile_task,
                native_news_task,
            )
            mover.name = str(facts.get("name") or profile.get("shortName") or profile.get("longName") or mover.name)
            mover.sector = str(facts.get("sector") or facts.get("sic_sector") or profile.get("sector") or mover.sector)
            mover.industry = str(
                facts.get("industry") or facts.get("sic_industry") or profile.get("industry") or mover.industry
            )
            mover.business_summary = str(
                facts.get("description")
                or facts.get("business_description")
                or profile.get("longBusinessSummary")
                or facts.get("sic_industry")
                or ""
            ).strip() or None
            fd_news = [self._format_financial_datasets_news(item) for item in news]
            if earnings:
                fd_news.insert(0, "近期披露财报或业绩更新。")
            if filings:
                fd_news.append("近期存在监管文件或公告更新。")
            mover.news_headlines = [line for line in fd_news + yahoo_news if line][:4]
        else:
            profile, yahoo_news = await asyncio.gather(native_profile_task, native_news_task)
            if profile:
                mover.name = str(profile.get("shortName") or profile.get("longName") or mover.name)
                mover.sector = str(profile.get("sector") or mover.sector)
                mover.industry = str(profile.get("industry") or mover.industry)
                mover.business_summary = str(profile.get("longBusinessSummary") or "").strip() or None
            mover.news_headlines = [line for line in yahoo_news if line][:4]

        if not mover.sector or mover.sector == "未分类":
            mover.sector = self._infer_sector_from_name(mover.name)
        if not mover.industry or mover.industry == "未分类":
            mover.industry = self._infer_industry_from_name(mover.name, mover.sector)
        mover.sector_zh = self._translate_sector(mover.sector)
        mover.industry_zh = self._translate_industry(mover.industry, mover.sector_zh)
        mover.catalyst = self._pick_catalyst(mover.news_headlines or [])

        mover.search_context = []
        if self.enable_public_search and self._should_use_public_search(mover):
            mover.search_context = await self._get_public_context(mover.symbol, mover.name, mover.market)
            if mover.search_context and not mover.news_headlines:
                mover.news_headlines = mover.search_context[:3]
        if not mover.catalyst:
            mover.catalyst = self._pick_catalyst(mover.news_headlines or [])

    async def _ai_label_movers(self, movers: list[MarketMover]) -> None:
        if not movers:
            return

        for start in range(0, len(movers), 8):
            batch = movers[start:start + 8]
            payload = [
                {
                    "symbol": mover.symbol,
                    "market": mover.market,
                    "name_en": mover.name,
                    "sector_hint": mover.sector,
                    "industry_hint": mover.industry,
                    "catalyst_hint": mover.catalyst,
                    "headline_hints": mover.news_headlines or [],
                    "business_summary": (mover.business_summary or "")[:1200],
                    "search_context": mover.search_context or [],
                }
                for mover in batch
            ]
            system = (
                "你是一名中英双语金融研究员。请根据股票英文名和提示，为每只股票补充常用中文名、"
                "中文一级分类、中文二级分类、公司一句话介绍、主要产品/业务、以及昨日上涨原因。"
                "输出严格 JSON，不要解释。尽量不要返回“未分类”、'待补充'、'未知' 这类占位词；"
                "如果公开资料有限，也要基于业务摘要与新闻线索给出尽量具体的中文表述。"
            )
            user = (
                '返回 JSON：{"items":[{"symbol":"", "name_zh":"", "sector_zh":"", "industry_zh":"", '
                '"company_intro":"", "main_products":"", "move_reason":""}]}\n'
                f"股票列表：{payload}"
            )
            try:
                response = await asyncio.wait_for(
                    self.ai_client.complete(system=system, user=user, max_tokens=2200),
                    timeout=45,
                )
                result = parse_json_response(response) or {}
            except Exception:
                result = {}

            enriched_map = {str(item.get("symbol")): item for item in result.get("items", []) if item.get("symbol")}
            for mover in batch:
                item = enriched_map.get(mover.symbol, {})
                mover.name_zh = str(item.get("name_zh") or mover.name_zh or "")
                mover.sector_zh = self._translate_sector(str(item.get("sector_zh") or mover.sector_zh or mover.sector))
                mover.industry_zh = self._translate_industry(
                    str(item.get("industry_zh") or mover.industry_zh or mover.industry),
                    mover.sector_zh,
                )
                mover.company_intro = str(item.get("company_intro") or mover.company_intro or "").strip() or None
                mover.main_products = str(item.get("main_products") or mover.main_products or "").strip() or None
                mover.move_reason = str(item.get("move_reason") or mover.move_reason or "").strip() or None
                self._apply_textual_fallbacks(mover)

    async def _ai_deepen_focus_movers(self, movers: list[MarketMover]) -> None:
        if not movers:
            return

        for mover in movers:
            payload = {
                "symbol": mover.symbol,
                "market": mover.market,
                "name_en": mover.name,
                "name_zh_hint": mover.name_zh,
                "sector_hint": mover.sector_zh or mover.sector,
                "industry_hint": mover.industry_zh or mover.industry,
                "business_summary": (mover.business_summary or "")[:1600],
                "news_headlines": (mover.news_headlines or [])[:4],
                "search_context": (mover.search_context or [])[:2],
            }
            system = (
                "你是一名中文卖方研究员。请基于公司业务摘要和新闻线索，为单只股票写出真正有信息量的三段内容："
                "公司是做什么的、主要产品/服务是什么、这次上涨的具体原因是什么。"
                "禁止输出空话，例如“主营方向与X相关”“主要产品与X业务相关”“资金围绕题材交易”。"
                "若缺乏明确催化，要明确写“暂无明确公司公告催化，更像板块/情绪驱动”，但仍要结合公司业务解释。"
                "只返回 JSON。"
            )
            user = (
                '返回 JSON：{"symbol":"","company_intro":"","main_products":"","move_reason":"","sector_zh":"","industry_zh":"","name_zh":""}\n'
                f"股票信息：{payload}"
            )
            try:
                response = await asyncio.wait_for(
                    self.ai_client.complete(system=system, user=user, max_tokens=1200),
                    timeout=25,
                )
                item = parse_json_response(response) or {}
            except Exception:
                item = {}
            if isinstance(item.get("items"), list) and item["items"]:
                item = item["items"][0] or {}

            company_intro = str(item.get("company_intro") or "").strip()
            main_products = str(item.get("main_products") or "").strip()
            move_reason = str(item.get("move_reason") or "").strip()
            if company_intro and not self._looks_generic(company_intro):
                mover.company_intro = company_intro
            if main_products and not self._looks_generic(main_products):
                mover.main_products = main_products
            if move_reason and not self._looks_generic(move_reason):
                mover.move_reason = move_reason
            if item.get("name_zh"):
                mover.name_zh = str(item.get("name_zh")).strip() or mover.name_zh
            if item.get("sector_zh"):
                mover.sector_zh = self._normalize_chinese_category(
                    str(item.get("sector_zh")),
                    fallback=self._translate_sector(mover.sector),
                )
            if item.get("industry_zh"):
                mover.industry_zh = self._normalize_chinese_category(
                    str(item.get("industry_zh")),
                    fallback=self._translate_industry(mover.industry, mover.sector_zh),
                )
            self._apply_textual_fallbacks(mover)

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
            "us_top": [self._brief_payload(item) for item in us_top[:8]],
            "hk_top": [self._brief_payload(item) for item in hk_top[:8]],
            "strongest_sector": strongest_sector,
            "strongest_industry": strongest_industry,
        }
        system = (
            "你是一名金融晨会纪要分析师。请基于涨幅榜、板块结构和已有催化，输出严格 JSON，"
            "要求结论清楚、中文表达直观。"
        )
        user = (
            "请输出 JSON："
            '{"market_summary":"一句话总览","catalysts":["原因1","原因2","原因3"],'
            '"heat_reasons":[{"sector":"板块名","reason":"为什么这个板块最热"}],'
            '"trend_outlook":"后续趋势判断","confidence_note":"如信号不足请说明"}\n\n'
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
            "heat_reasons": result.get("heat_reasons") or fallback["heat_reasons"],
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
        return {
            "market_summary": (
                f"昨日美股整体强于港股，热度集中在 {strongest_sector} / {strongest_industry}。"
                if avg_us >= avg_hk
                else f"昨日港股整体强于美股，热度集中在 {strongest_sector} / {strongest_industry}。"
            ),
            "catalysts": [
                "高弹性成长股集体走强，说明短线风险偏好明显回升。",
                "上榜个股集中在科技、能源或题材股，更多体现交易型资金抱团。",
                "公开公告与新闻信号不足，部分走势仍可能是事件驱动后的情绪放大。",
            ],
            "heat_reasons": [
                {"sector": strongest_sector, "reason": "该方向上榜公司最多，且平均涨幅领先，说明资金集中度最高。"},
            ],
            "trend_outlook": (
                f"{strongest_sector} 方向短线仍可能延续，但更大概率出现“主线延续、个股分化”结构；"
                "判断关键在于次日是否继续放量、龙头是否保持强势。"
            ),
            "confidence_note": f"当前总龙头是 {leader}，但公开新闻不足，结论主要基于榜单结构与涨幅分布。",
        }

    def _build_heat_ranking_lines(self, movers: list[MarketMover], heat_reasons: Optional[list[dict[str, Any]]] = None) -> list[str]:
        ranking = rank_heat_groups(
            [
                {
                    "sector_zh": mover.sector_zh,
                    "change_pct": mover.change_pct,
                    "symbol": mover.symbol,
                    "display_name": mover.display_name,
                }
                for mover in movers
            ],
            "sector_zh",
            top_n=5,
        )
        reason_map = {
            str(item.get("sector") or "").strip(): str(item.get("reason") or "").strip()
            for item in (heat_reasons or [])
            if item.get("sector") and item.get("reason")
        }
        return [
            (
                f"{index}. {item['label']}：{item['count']} 家上榜，平均 {item['avg_change']:+.2f}% ，"
                f"龙头 {item['leader_symbol']}（{item['leader_name']}）"
                + (
                    f"\n   热点原因：{reason_map[item['label']]}"
                    if reason_map.get(item["label"])
                    else ""
                )
            )
            for index, item in enumerate(ranking, start=1)
        ] or ["- 暂无热度排名"]

    def _build_overview_points(
        self,
        us_top: list[MarketMover],
        hk_top: list[MarketMover],
        strongest_sector: str,
        leader: str,
    ) -> list[str]:
        us_focus = pick_strongest_group([asdict(item) for item in us_top], "sector_zh")
        hk_focus = pick_strongest_group([asdict(item) for item in hk_top], "sector_zh")
        return [
            f"美股主线：{us_focus}。",
            f"港股主线：{hk_focus}。",
            f"全市场热度最高方向：{strongest_sector}。",
            f"当前总龙头：{leader}。",
        ]

    @staticmethod
    def _pick_leader(movers: list[MarketMover], strongest_sector: str) -> str:
        preferred = [item for item in movers if item.sector_zh == strongest_sector] or movers
        leader = max(preferred, key=lambda item: item.change_pct, default=None)
        if leader is None:
            return "暂无明显龙头"
        return f"{leader.symbol}（{leader.display_name}，{leader.change_pct:+.2f}%）"

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
    def _translate_sector(sector: str) -> str:
        normalized = sector.strip()
        return SECTOR_ZH_MAP.get(normalized, normalized if normalized != "未分类" else "未分类")

    @staticmethod
    def _translate_industry(industry: str, sector_zh: str) -> str:
        normalized = industry.strip()
        if normalized == "未分类":
            return sector_zh
        return SECTOR_ZH_MAP.get(normalized, normalized)

    @staticmethod
    def _brief_payload(mover: MarketMover) -> dict[str, Any]:
        return {
            "symbol": mover.symbol,
            "name": mover.name,
            "name_zh": mover.name_zh,
            "change_pct": mover.change_pct,
            "sector_zh": mover.sector_zh,
            "industry_zh": mover.industry_zh,
            "catalyst": mover.catalyst,
            "company_intro": mover.company_intro,
            "main_products": mover.main_products,
            "move_reason": mover.move_reason,
        }

    @staticmethod
    def _fetch_yahoo_profile(symbol: str) -> dict[str, Any]:
        if yf is None:
            return {}
        try:
            return yf.Ticker(symbol).info or {}
        except Exception:
            return {}

    @staticmethod
    def _fetch_yahoo_news(symbol: str) -> list[str]:
        if yf is None:
            return []
        try:
            items = yf.Ticker(symbol).news or []
        except Exception:
            return []

        headlines: list[str] = []
        for item in items[:4]:
            content = item.get("content") or {}
            title = str(content.get("title") or item.get("title") or "").strip()
            summary = str(content.get("summary") or item.get("summary") or "").strip()
            line = " - ".join(part for part in [title, summary] if part)
            cleaned = FinanceDigestRunner._clean_external_snippet(line)
            if cleaned:
                headlines.append(cleaned)
        return headlines[:4]

    @staticmethod
    def _format_financial_datasets_news(item: dict[str, Any]) -> str:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or item.get("snippet") or "").strip()
        line = " - ".join(part for part in [title, summary] if part)
        return FinanceDigestRunner._clean_external_snippet(line)

    @staticmethod
    def _search_public_context(symbol: str, name: str, market: str) -> list[str]:
        queries = [f"{symbol} {name} {'Hong Kong' if market == 'hk' else 'US'} stock latest news products"]
        snippets: list[str] = []
        stderr = sys.stderr
        sys.stderr = open(os.devnull, "w")
        try:
            ddgs = DDGS()
            for query in queries:
                try:
                    results = ddgs.text(query, max_results=2)
                except Exception:
                    continue
                for item in results or []:
                    title = str(item.get("title") or "").strip()
                    body = str(item.get("body") or "").strip()
                    line = " - ".join(part for part in [title, body] if part)
                    if line and line not in snippets:
                        snippets.append(line[:280])
        finally:
            sys.stderr.close()
            sys.stderr = stderr
        return snippets[:4]

    async def _get_public_context(self, symbol: str, name: str, market: str) -> list[str]:
        async with self.search_semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._search_public_context, symbol, name, market),
                    timeout=12,
                )
            except Exception:
                return []

    def _should_use_public_search(self, mover: MarketMover) -> bool:
        if mover.market == "us" and mover.news_headlines and mover.business_summary:
            return False
        return not mover.news_headlines or not mover.business_summary

    def _apply_textual_fallbacks(self, mover: MarketMover) -> None:
        mover.sector_zh = self._translate_sector(mover.sector_zh or mover.sector)
        mover.industry_zh = self._translate_industry(mover.industry_zh or mover.industry, mover.sector_zh)

        context_blocks = [mover.business_summary or ""] + (mover.news_headlines or []) + (mover.search_context or [])
        context = " ".join(block for block in context_blocks if block).strip()
        sentences = [part.strip(" -") for part in re.split(r"(?<=[。.!?])\s+|\s+-\s+", context) if part.strip(" -")]

        if not mover.company_intro:
            mover.company_intro = self._pick_context_sentence(
                sentences,
                ["company", "provides", "develops", "designs", "operator", "provider", "制造", "提供", "主营"],
            ) or (sentences[0][:100] if sentences else f"{mover.name} 所处方向为 {mover.industry_zh or mover.sector_zh}。")

        if not mover.main_products:
            mover.main_products = self._pick_context_sentence(
                sentences,
                ["product", "products", "services", "platform", "launch", "vehicle", "software", "equipment", "芯片", "产品", "服务"],
            ) or mover.company_intro

        if not mover.move_reason:
            mover.move_reason = (
                mover.catalyst
                or self._pick_context_sentence(
                    sentences,
                    ["surge", "rose", "rally", "contract", "earnings", "guidance", "launch", "news", "gain", "财报", "订单", "合同", "催化"],
                )
                or "公开信息显示资金主要围绕相关业务主题与短线催化集中交易。"
            )

        mover.sector_zh = self._normalize_chinese_category(mover.sector_zh, fallback=self._translate_sector(mover.sector))
        mover.industry_zh = self._normalize_chinese_category(
            mover.industry_zh,
            fallback=self._translate_industry(mover.industry, mover.sector_zh),
        )
        mover.company_intro = self._normalize_chinese_text(
            mover.company_intro or "",
            fallback=f"{mover.name} 主营方向与 {mover.industry_zh or mover.sector_zh} 相关。",
        )
        mover.main_products = self._normalize_chinese_text(
            mover.main_products or "",
            fallback=f"公司主要产品与 {mover.industry_zh or mover.sector_zh} 业务相关。",
        )
        mover.move_reason = self._normalize_chinese_text(
            mover.move_reason or "",
            fallback="公开信息显示资金主要围绕相关业务主题与短线催化集中交易。",
        )

    @staticmethod
    def _clean_external_snippet(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if not normalized:
            return ""
        normalized = re.sub(r"\|\s*Reuters.*$", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\|\s*TipRanks.*$", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"Stock Price & Latest News.*$", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"View the latest .*?$", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"Get the latest .*?$", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+-\s+$", "", normalized)
        return normalized[:220]

    @staticmethod
    def _pick_context_sentence(sentences: list[str], keywords: list[str]) -> Optional[str]:
        lowered_keywords = [keyword.lower() for keyword in keywords]
        for sentence in sentences:
            lowered = sentence.lower()
            if any(keyword in lowered for keyword in lowered_keywords):
                return sentence[:140]
        return sentences[0][:140] if sentences else None

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", text or ""))

    def _needs_chinese_rewrite(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return True
        if "未分类" in normalized or "待补充" in normalized:
            return True
        return not self._contains_chinese(normalized)

    def _mover_needs_localization(self, mover: MarketMover) -> bool:
        return any(
            self._needs_chinese_rewrite(value)
            for value in [
                mover.sector_zh,
                mover.industry_zh,
                mover.company_intro,
                mover.main_products,
                mover.move_reason,
            ]
        )

    def _normalize_chinese_category(self, text: str, fallback: str) -> str:
        normalized = (text or "").strip()
        if self._needs_chinese_rewrite(normalized):
            fallback_text = self._translate_sector(fallback.strip()) if fallback.strip() else ""
            if fallback_text and fallback_text != "未分类" and self._contains_chinese(fallback_text):
                return fallback_text
            return "综合企业"
        return normalized

    def _normalize_chinese_text(self, text: str, fallback: str) -> str:
        normalized = (text or "").strip()
        if self._needs_chinese_rewrite(normalized):
            fallback_text = (fallback or "").strip()
            if self._contains_chinese(fallback_text):
                return fallback_text
            return "公开信息显示公司业务与近期市场关注主题相关，资金围绕该方向集中交易。"
        return normalized

    @staticmethod
    def _looks_generic(text: str) -> bool:
        normalized = (text or "").strip()
        generic_markers = [
            "主营方向与",
            "主要产品与",
            "业务相关",
            "资金主要围绕",
            "题材与资金偏好",
            "短线催化集中交易",
        ]
        return any(marker in normalized for marker in generic_markers)

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
            "Technology": ["tech", "software", "semi", "chip", "cloud", "ai", "internet", "digital", "data"],
            "Healthcare": ["pharma", "bio", "medical", "health", "hospital", "drug"],
            "Financials": ["bank", "financial", "insurance", "capital", "securities", "broker"],
            "Energy": ["energy", "oil", "gas", "solar", "power", "battery"],
            "Materials": ["mining", "metal", "steel", "lithium", "gold", "copper", "cement"],
            "Consumer": ["retail", "food", "beverage", "auto", "motor", "consumer", "travel", "golf"],
            "Industrials": ["shipping", "logistics", "air", "aerospace", "industrial", "machinery", "space"],
            "Real Estate": ["property", "real estate", "reit"],
            "Communication Services": ["media", "communication", "telecom", "network"],
        }
        for sector, hints in sector_keywords.items():
            if any(hint in lowered for hint in hints):
                return sector
        return "未分类"

    @staticmethod
    def _infer_industry_from_name(name: str, sector: str) -> str:
        lowered = name.lower()
        if sector == "Technology":
            if any(keyword in lowered for keyword in ["semi", "chip", "micron", "maxlinear", "navitas", "synaptics"]):
                return "Semiconductors"
            if any(keyword in lowered for keyword in ["cloud", "software", "dropbox", "akamai", "jfrog"]):
                return "Software"
            if any(keyword in lowered for keyword in ["data", "innodata"]):
                return "Data Infrastructure"
        if sector == "Industrials" and any(keyword in lowered for keyword in ["space", "rocket", "firefly", "redwire"]):
            return "Aerospace & Defense"
        if sector == "Energy" and any(keyword in lowered for keyword in ["fluence", "eos", "solar", "battery"]):
            return "Energy Storage"
        if sector == "Communication Services" and any(keyword in lowered for keyword in ["network", "telecom"]):
            return "Network Equipment"
        return sector if sector != "未分类" else "未分类"
