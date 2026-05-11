"""Summarizers for finance and AI digest messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FinanceDigestSummary:
    date: str
    market_summary: str
    us_top_movers: list[Any]
    hk_top_movers: list[Any]
    strongest_sector: str
    strongest_industry: str
    leader: Any
    catalysts: list[str]
    trend_outlook: str
    confidence_note: str


@dataclass
class AiDigestSummary:
    date: str
    headline: str
    github_trending: list[Any]
    product_hunt: list[Any]
    category_breakdown: Any
    notable_projects: list[Any]
    trend_outlook: str


class FinanceSummarizer:
    """Render a finance digest summary as markdown."""

    def render(self, summary: FinanceDigestSummary) -> str:
        lines = [
            f"# 金融日报 | {summary.date}",
            "",
            summary.market_summary,
            "",
            "## 昨日美股 Top 20",
            "",
        ]
        lines.extend(self._render_movers(summary.us_top_movers))
        lines.extend(["", "## 昨日港股 Top 20", ""])
        lines.extend(self._render_movers(summary.hk_top_movers))
        lines.extend(
            [
                "",
                "## 最强板块与龙头",
                "",
                f"- 最强板块：{summary.strongest_sector}",
                f"- 最强细分行业：{summary.strongest_industry}",
                f"- 龙头：{self._render_leader(summary.leader)}",
                "",
                "## 上涨原因归因",
                "",
            ]
        )
        lines.extend([f"- {item}" for item in summary.catalysts] or ["- 暂无明确催化"])
        lines.extend(["", "## 后续趋势判断", "", summary.trend_outlook, "", summary.confidence_note])
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _render_movers(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["- 暂无数据"]

        rendered = []
        for item in items:
            if isinstance(item, str):
                rendered.append(item)
                continue
            rendered.append(
                "- {name} ({symbol}) {change_pct}% | {sector} / {industry}".format(
                    name=item.get("name", item.get("symbol", "未知标的")),
                    symbol=item.get("symbol", ""),
                    change_pct=item.get("change_pct", ""),
                    sector=item.get("sector", "未知板块"),
                    industry=item.get("industry", "未知行业"),
                )
            )
        return rendered

    @staticmethod
    def _render_leader(leader: Any) -> str:
        if isinstance(leader, str):
            return leader
        if isinstance(leader, dict):
            return (
                f"{leader.get('name', leader.get('symbol', ''))} "
                f"({leader.get('symbol', '')}) {leader.get('change_pct', '')}%"
            ).strip()
        return "暂无明显龙头"


class AiSummarizer:
    """Render an AI digest summary as markdown."""

    def render(self, summary: AiDigestSummary) -> str:
        lines = [
            f"# AI 日报 | {summary.date}",
            "",
            summary.headline,
            "",
            "## GitHub Trending Top 20",
            "",
        ]
        lines.extend(self._render_projects(summary.github_trending))
        lines.extend(["", "## Product Hunt Top 20", ""])
        lines.extend(self._render_projects(summary.product_hunt))
        lines.extend(["", "## 分类概览", ""])
        if isinstance(summary.category_breakdown, dict):
            lines.extend([f"- {category}: {count}" for category, count in summary.category_breakdown.items()])
        else:
            lines.extend(list(summary.category_breakdown))
        lines.extend(["", "## 值得关注的项目", ""])
        for project in summary.notable_projects:
            if isinstance(project, str):
                lines.append(f"- {project}")
                continue
            lines.append(
                "- {name} [{source}] | {category} | {reason}".format(
                    name=project.get("name", "未知项目"),
                    source=project.get("source", "unknown"),
                    category=project.get("category", "未分类"),
                    reason=project.get("reason", ""),
                )
            )
        lines.extend(["", "## 后续趋势判断", "", summary.trend_outlook])
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _render_projects(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["- 暂无数据"]

        rendered = []
        for item in items:
            if isinstance(item, str):
                rendered.append(item)
                continue
            rendered.append(
                "- {name} | {category} | {why}".format(
                    name=item.get("name", "未知项目"),
                    category=item.get("category", "未分类"),
                    why=item.get("why_interesting", item.get("description", "")),
                )
            )
        return rendered
