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
        market_groups=[
            {
                "title": "美股分类看板",
                "groups": [
                    {
                        "heading": "科技（2家｜平均 +7.15%｜龙头 NVDA）",
                        "items": [
                            "1. [`NVDA`](https://finance.yahoo.com/quote/NVDA) NVIDIA（英伟达） | +8.20% | 半导体\n   主营：全球领先的 AI 芯片公司。\n   核心产品：GPU、AI 加速卡。\n   催化：财报与资本开支指引超预期。\n   判断：更像基本面兑现，不只是题材炒作。",
                            "2. [`AMD`](https://finance.yahoo.com/quote/AMD) AMD（超威半导体） | +5.20% | 半导体\n   主营：高性能 CPU/GPU 供应商。\n   核心产品：数据中心 GPU、服务器 CPU。\n   催化：算力链预期继续走强。\n   判断：行业景气仍强，关注后续订单验证。",
                        ],
                    }
                ],
            },
            {
                "title": "港股分类看板",
                "groups": [
                    {
                        "heading": "通信服务（1家｜平均 +6.10%｜龙头 0700.HK）",
                        "items": [
                            "1. [`0700.HK`](https://finance.yahoo.com/quote/0700.HK) Tencent（腾讯） | +6.10% | 互联网平台\n   主营：中国头部互联网平台。\n   核心产品：微信、游戏、云服务。\n   催化：游戏与广告预期改善。\n   判断：基本面修复逻辑增强。",
                        ],
                    }
                ],
            },
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
    assert "## 美股分类看板" in result
    assert "## 港股分类看板" in result
    assert "### 科技（2家｜平均 +7.15%｜龙头 NVDA）" in result
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
        category_breakdown={
            "智能体": 8,
            "开发工具": 5,
        },
        category_groups=[
            {
                "heading": "智能体（8个项目｜GitHub 5｜PH 3）",
                "items": [
                    "1. [org/repo-a](https://github.com/org/repo-a) | GitHub #1\n   项目定位：多代理任务编排框架。\n   核心能力：浏览器自动化、工作流自动化。\n   看点：工程化完成度明显提升。\n   判断：代表智能体工程化继续升温。",
                ],
            },
            {
                "heading": "开发工具（5个项目｜GitHub 2｜PH 3）",
                "items": [
                    "1. [Product A](https://producthunt.com/posts/a) | Product Hunt #2\n   项目定位：把模型调用封装成开发工具。\n   核心能力：开发工具、效率办公。\n   看点：产品化方向清晰。\n   判断：更适合工具链落地场景。",
                ],
            },
        ],
        notable_projects=[
            "org/repo-a：围绕 browser use 的工程化明显成熟。"
        ],
        trend_outlook="Agent 工作流和编程工具继续合流，短期会看到更多 infra 层产品化。",
    )

    result = AiSummarizer().render(summary)

    assert "# AI 日报 | 2026-05-10" in result
    assert "## 分类热度榜" in result
    assert "## 分类项目看板" in result
    assert "### 智能体（8个项目｜GitHub 5｜PH 3）" in result
    assert "## 后续趋势判断" in result
    assert "org/repo-a" in result
    assert "Product A" in result
    assert "智能体" in result
    assert "Agent 工作流" in result
