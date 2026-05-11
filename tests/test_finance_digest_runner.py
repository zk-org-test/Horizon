import asyncio
from unittest.mock import AsyncMock, Mock, patch

import httpx

from src.digests.finance_runner import FinanceDigestRunner, MarketMover
from src.models import FinanceDigestConfig


def test_enrich_mover_uses_yahoo_profile_for_hk_classification():
    runner = FinanceDigestRunner(FinanceDigestConfig(enabled=True, top_n=5), Mock(), httpx.AsyncClient())
    mover = MarketMover(symbol="0482.HK", name="SANDMARTIN INTL", market="hk", change_pct=27.42)

    with patch.object(
        FinanceDigestRunner,
        "_fetch_yahoo_profile",
        return_value={
            "shortName": "Sandmartin International",
            "sector": "Technology",
            "industry": "Communication Equipment",
            "longBusinessSummary": "Sandmartin makes communication equipment and set-top-box products.",
        },
    ), patch.object(
        FinanceDigestRunner,
        "_fetch_yahoo_news",
        return_value=[
            "Sandmartin announced new communication hardware products.",
            "Investors focused on communication equipment demand recovery.",
        ],
    ):
        asyncio.run(runner._enrich_mover(mover))

    asyncio.run(runner.http_client.aclose())

    assert mover.sector_zh == "科技"
    assert mover.industry_zh == "通信设备"
    assert mover.business_summary
    assert mover.news_headlines


def test_enrich_mover_prefers_native_yahoo_news_over_public_search_noise():
    runner = FinanceDigestRunner(FinanceDigestConfig(enabled=True, top_n=5), Mock(), httpx.AsyncClient())
    mover = MarketMover(symbol="3816.HK", name="KFM KINGDOM", market="hk", change_pct=28.92)

    with patch.object(
        FinanceDigestRunner,
        "_fetch_yahoo_profile",
        return_value={
            "shortName": "KFM Kingdom",
            "sector": "Industrials",
            "industry": "Metal Fabrication",
            "longBusinessSummary": "KFM Kingdom is a metal stamping and precision metal processing company.",
        },
    ), patch.object(
        FinanceDigestRunner,
        "_fetch_yahoo_news",
        return_value=[
            "KFM Kingdom reported stronger orders from precision metal customers.",
            "Metal processing demand improved across industrial names.",
        ],
    ), patch.object(FinanceDigestRunner, "_get_public_context", return_value=[]):
        asyncio.run(runner._enrich_mover(mover))

    asyncio.run(runner.http_client.aclose())

    assert mover.news_headlines
    assert "Reuters" not in mover.news_headlines[0]
    assert mover.catalyst


def test_apply_textual_fallbacks_uses_summary_and_search_context():
    runner = FinanceDigestRunner(FinanceDigestConfig(enabled=True, top_n=5), Mock(), httpx.AsyncClient())
    mover = MarketMover(symbol="RKLB", name="Rocket Lab", market="us", change_pct=34.44)
    mover.business_summary = (
        "Rocket Lab is a space systems company that provides launch services, spacecraft components, "
        "and space software."
    )
    mover.news_headlines = [
        "Rocket Lab reported record revenue and raised full-year guidance.",
        "Rocket Lab won fresh defense and launch contracts.",
    ]
    mover.search_context = [
        "Rocket Lab won fresh defense and launch contracts.",
        "Its Electron launch vehicle and satellite systems remain the main products.",
    ]

    runner._apply_textual_fallbacks(mover)
    asyncio.run(runner.http_client.aclose())

    assert mover.company_intro
    assert mover.main_products
    assert "主营方向与" not in mover.company_intro
    assert "主要产品与" not in mover.main_products
    assert "资金主要围绕" not in mover.move_reason
    assert any(keyword in mover.company_intro for keyword in ["太空系统", "发射服务", "航天"])
    assert any(keyword in mover.main_products for keyword in ["发射服务", "航天器", "软件"])
    assert any(keyword in mover.move_reason for keyword in ["业绩", "指引", "合同"])
    assert mover.move_reason


def test_apply_compact_fields_prefers_short_summary_over_raw_truncation():
    runner = FinanceDigestRunner(FinanceDigestConfig(enabled=True, top_n=5), Mock(), httpx.AsyncClient())
    mover = MarketMover(symbol="INOD", name="Innodata", market="us", change_pct=12.3)
    mover.company_intro = "Innodata是一家数据工程与AI数据服务公司，为大模型训练、对齐和评测提供数据处理与交付能力。"
    mover.main_products = "数字数据解决方案、结构化医疗数据平台和媒体情报SaaS，覆盖训练数据、模型评测和内容分析。"
    mover.move_reason = "公司公布创纪录季度业绩，营收和盈利超预期并上调全年增长指引，同时披露大客户新订单进展。"

    runner._apply_compact_fields(mover)
    asyncio.run(runner.http_client.aclose())

    assert mover.company_intro.startswith("Innodata是一家数据工程与AI数据服务公司")
    assert mover.main_products.startswith("数字数据解决方案")
    assert mover.move_reason.startswith("公司公布创纪录季度业绩")
    assert len(mover.company_intro) <= 40
    assert len(mover.main_products) <= 40
    assert len(mover.move_reason) <= 42


def test_needs_chinese_rewrite_flags_english_and_unclassified_content():
    runner = FinanceDigestRunner(FinanceDigestConfig(enabled=True, top_n=5), Mock(), httpx.AsyncClient())

    assert runner._needs_chinese_rewrite("This is an English sentence.")
    assert runner._needs_chinese_rewrite("未分类")
    assert not runner._needs_chinese_rewrite("这是一段中文总结。")

    asyncio.run(runner.http_client.aclose())


def test_clean_external_snippet_removes_search_result_boilerplate():
    cleaned = FinanceDigestRunner._clean_external_snippet(
        "(3816.HK) | Stock Price & Latest News | Reuters - Get KFM Kingdom Holdings Ltd real-time stock quotes"
    )

    assert "Reuters" not in cleaned
    assert "Stock Price & Latest News" not in cleaned


def test_ai_deepen_focus_movers_overrides_generic_fallback_text():
    ai_client = Mock()
    ai_client.complete = AsyncMock(
        return_value='{"items":[{"symbol":"INOD","company_intro":"Innodata 是一家 AI 数据工程公司。","main_products":"AI 训练数据与媒体情报 SaaS。","move_reason":"创纪录业绩并上调指引推动上涨。","judgment":"更像基本面兑现，不只是题材炒作。"}]}'
    )
    runner = FinanceDigestRunner(FinanceDigestConfig(enabled=True, top_n=5), ai_client, httpx.AsyncClient())
    mover = MarketMover(symbol="INOD", name="Innodata Inc", market="us", change_pct=85.75)
    mover.company_intro = "Innodata Inc 主营方向与 IT服务相关。"
    mover.main_products = "公司主要产品与 IT服务业务相关。"
    mover.move_reason = "公开信息显示资金主要围绕相关业务主题与短线催化集中交易。"
    mover.business_summary = "Innodata provides AI training data and data engineering services."
    mover.news_headlines = ["Record quarter and raised full-year guidance."]

    asyncio.run(runner._ai_deepen_focus_movers([mover]))
    asyncio.run(runner.http_client.aclose())

    assert mover.company_intro.startswith("Innodata 是一家 AI 数据工程公司")
    assert mover.main_products.startswith("AI 训练数据与媒体情报 SaaS")
    assert mover.move_reason.startswith("创纪录业绩并上调指引推动上涨")
    assert mover.judgment.startswith("更像基本面兑现")


def test_ai_label_movers_ignores_generic_ai_output_and_keeps_specific_fallbacks():
    ai_client = Mock()
    ai_client.complete = AsyncMock(
        return_value='{"items":[{"symbol":"RKLB","company_intro":"Rocket Lab 主营方向与 航空航天与国防 相关。","main_products":"公司主要产品与 航空航天与国防 业务相关。","move_reason":"公开信息显示资金主要围绕相关业务主题与短线催化集中交易。"}]}'
    )
    runner = FinanceDigestRunner(FinanceDigestConfig(enabled=True, top_n=5), ai_client, httpx.AsyncClient())
    mover = MarketMover(symbol="RKLB", name="Rocket Lab Corporation", market="us", change_pct=34.44)
    mover.sector = "Industrials"
    mover.industry = "Aerospace & Defense"
    mover.sector_zh = "工业"
    mover.industry_zh = "航空航天与国防"
    mover.business_summary = (
        "Rocket Lab is a space systems company that provides launch services, spacecraft components, "
        "and space software."
    )
    mover.news_headlines = [
        "Rocket Lab reported record revenue and raised full-year guidance.",
    ]

    asyncio.run(runner._ai_label_movers([mover]))
    asyncio.run(runner.http_client.aclose())

    assert "主营方向与" not in mover.company_intro
    assert "主要产品与" not in mover.main_products
    assert "资金主要围绕" not in mover.move_reason
