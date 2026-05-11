"""Summarizers for finance and AI digest messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FinanceDigestSummary:
    date: str
    market_summary: str
    overview_points: list[str]
    heat_rankings: list[str]
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
            f"> {summary.market_summary}",
            "",
            "## 先看结论",
            "",
        ]
        lines.extend([f"- {item}" for item in summary.overview_points] or ["- 暂无结论"])
        lines.extend(["", "## 板块热度榜", ""])
        lines.extend(summary.heat_rankings or ["- 暂无热度排名"])
        lines.extend(["", "## 昨日美股 Top 20 焦点", ""])
        lines.extend(self._render_lines(summary.us_top_movers))
        lines.extend(["", "## 昨日港股 Top 20 焦点", ""])
        lines.extend(self._render_lines(summary.hk_top_movers))
        lines.extend(
            [
                "",
                "## 核心龙头",
                "",
                f"- 最强板块：{summary.strongest_sector}",
                f"- 最强细分行业：{summary.strongest_industry}",
                f"- 总龙头：{self._render_leader(summary.leader)}",
                "",
                "## 上涨原因归因",
                "",
            ]
        )
        lines.extend([f"- {item}" for item in summary.catalysts] or ["- 暂无明确催化"])
        lines.extend(["", "## 后续趋势判断", "", summary.trend_outlook, "", summary.confidence_note])
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _render_lines(items: list[Any]) -> list[str]:
        if not items:
            return ["- 暂无数据"]
        rendered: list[str] = []
        for item in items:
            if isinstance(item, str):
                rendered.append(item)
            else:
                rendered.append(str(item))
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
