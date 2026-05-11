"""Unit tests for finance and AI digest summarizers."""

from __future__ import annotations

from src.digests.summarizers import (
    AiDigestSummary,
    AiSummarizer,
    FinanceDigestSummary,
    FinanceSummarizer,
)


def test_finance_summarizer_renders_required_sections():
    summary = FinanceDigestSummary(
        date="2026-05-10",
        market_summary="昨夜美股风险偏好回暖，港股科技链条领涨。",
        us_top_movers=[
            {"symbol": "NVDA", "name": "NVIDIA", "change_pct": 8.2, "sector": "Technology", "industry": "Semiconductors"}
        ],
        hk_top_movers=[
            {"symbol": "0700.HK", "name": "Tencent", "change_pct": 6.1, "sector": "Communication Services", "industry": "Internet Content & Information"}
        ],
        strongest_sector="Technology",
        strongest_industry="Semiconductors",
        leader={
            "symbol": "NVDA",
            "name": "NVIDIA",
            "change_pct": 8.2,
        },
        catalysts=[
            "财报与资本开支指引超预期",
            "AI 基础设施链条继续强化",
        ],
        trend_outlook="延续：龙头放量领涨，短期趋势仍强，但需要关注高位波动。",
        confidence_note="公开新闻信号充足，结论置信度中高。",
    )

    result = FinanceSummarizer().render(summary)

    assert "# 金融日报 | 2026-05-10" in result
    assert "## 昨日美股 Top 20" in result
    assert "## 昨日港股 Top 20" in result
    assert "## 最强板块与龙头" in result
    assert "## 上涨原因归因" in result
    assert "## 后续趋势判断" in result
    assert "NVIDIA" in result
    assert "Tencent" in result
    assert "Technology" in result
    assert "延续" in result


def test_ai_summarizer_renders_required_sections():
    summary = AiDigestSummary(
        date="2026-05-10",
        headline="今天的主线是 agent tooling 和开发基础设施。",
        github_trending=[
            {"name": "org/repo-a", "category": "Agent", "why_interesting": "多代理任务编排更完整"}
        ],
        product_hunt=[
            {"name": "Product A", "category": "DevTool", "why_interesting": "把模型调用与工具链封装成产品"}
        ],
        category_breakdown={
            "Agent": 8,
            "DevTool": 5,
        },
        notable_projects=[
            {
                "name": "org/repo-a",
                "source": "github",
                "category": "Agent",
                "reason": "围绕 browser use 的工程化明显成熟",
            }
        ],
        trend_outlook="Agent 工作流和编程工具继续合流，短期会看到更多 infra 层产品化。",
    )

    result = AiSummarizer().render(summary)

    assert "# AI 日报 | 2026-05-10" in result
    assert "## GitHub Trending Top 20" in result
    assert "## Product Hunt Top 20" in result
    assert "## 分类概览" in result
    assert "## 值得关注的项目" in result
    assert "## 后续趋势判断" in result
    assert "org/repo-a" in result
    assert "Product A" in result
    assert "Agent 工作流" in result
