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
            "1. 科技：2 家上榜，平均 +7.15%，龙头 NVDA\n   热点原因：算力链与资本开支预期共振。",
        ],
        us_focus_movers=[
            "1. [`NVDA`](https://finance.yahoo.com/quote/NVDA) NVIDIA（英伟达） | +8.20% | 分类：科技 / 半导体\n   公司：全球领先的 AI 芯片公司。\n   产品：GPU、AI 加速卡。\n   走强原因：财报与资本开支指引超预期。",
        ],
        hk_focus_movers=[
            "1. [`0700.HK`](https://finance.yahoo.com/quote/0700.HK) Tencent（腾讯） | +6.10% | 分类：通信服务 / 互联网平台\n   公司：中国头部互联网平台。\n   产品：微信、游戏、云服务。\n   走强原因：游戏与广告预期改善。",
        ],
        us_more_movers=["6. [`AMD`](https://finance.yahoo.com/quote/AMD) AMD（超威半导体） | +5.20% | 分类：科技 / 半导体"],
        hk_more_movers=["6. [`1810.HK`](https://finance.yahoo.com/quote/1810.HK) Xiaomi（小米） | +4.10% | 分类：可选消费 / 消费电子"],
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
    assert "## 昨日美股重点公司" in result
    assert "## 其余美股上榜速览" in result
    assert "## 昨日港股重点公司" in result
    assert "## 其余港股上榜速览" in result
    assert "## 上涨原因归因" in result
    assert "## 后续趋势判断" in result
    assert "https://finance.yahoo.com/quote/NVDA" in result
    assert "NVIDIA" in result
    assert "腾讯" in result
    assert "科技" in result
    assert "延续" in result


def test_ai_summarizer_renders_required_sections():
    summary = AiDigestSummary(
        date="2026-05-10",
        headline="今天的主线是 agent tooling 和开发基础设施。",
        github_trending=[
            {"name": "org/repo-a", "category": "智能体", "why_interesting": "多代理任务编排更完整"}
        ],
        product_hunt=[
            {"name": "Product A", "category": "开发工具", "why_interesting": "把模型调用与工具链封装成产品"}
        ],
        category_breakdown={
            "智能体": 8,
            "开发工具": 5,
        },
        notable_projects=[
            {
                "name": "org/repo-a",
                "source": "github",
                "category": "智能体",
                "reason": "围绕 browser use 的工程化明显成熟",
            }
        ],
        trend_outlook="Agent 工作流和编程工具继续合流，短期会看到更多 infra 层产品化。",
    )

    result = AiSummarizer().render(summary)

    assert "# AI 日报 | 2026-05-10" in result
    assert "## GitHub Trending 榜单" in result
    assert "## Product Hunt 榜单" in result
    assert "## 分类热度榜" in result
    assert "## 值得关注的项目" in result
    assert "## 后续趋势判断" in result
    assert "org/repo-a" in result
    assert "Product A" in result
    assert "智能体" in result
    assert "Agent 工作流" in result
