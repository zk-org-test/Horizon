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
        overview_points=[
            "美股主线：算力与半导体继续领涨。",
            "港股主线：平台与云基础设施回暖。",
        ],
        heat_rankings=[
            "1. 科技：2 家上榜，平均 +7.15%，龙头 NVDA",
        ],
        us_top_movers=[
            "1. `NVDA` NVIDIA（英伟达） | +8.20% | 科技 / 半导体",
        ],
        hk_top_movers=[
            "1. `0700.HK` Tencent（腾讯） | +6.10% | 通信服务 / 互联网平台",
        ],
        strongest_sector="科技",
        strongest_industry="半导体",
        leader="NVDA（NVIDIA / 英伟达） +8.20%",
        catalysts=[
            "财报与资本开支指引超预期",
            "AI 基础设施链条继续强化",
        ],
        trend_outlook="延续：龙头放量领涨，短期趋势仍强，但需要关注高位波动。",
        confidence_note="公开新闻信号充足，结论置信度中高。",
    )

    result = FinanceSummarizer().render(summary)

    assert "# 金融日报 | 2026-05-10" in result
    assert "## 先看结论" in result
    assert "## 板块热度榜" in result
    assert "## 昨日美股 Top 20 焦点" in result
    assert "## 昨日港股 Top 20 焦点" in result
    assert "## 上涨原因归因" in result
    assert "## 后续趋势判断" in result
    assert "NVIDIA" in result
    assert "腾讯" in result
    assert "科技" in result
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
