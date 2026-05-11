import asyncio
from unittest.mock import Mock, patch

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
    mover.search_context = [
        "Rocket Lab won fresh defense and launch contracts.",
        "Its Electron launch vehicle and satellite systems remain the main products.",
    ]

    runner._apply_textual_fallbacks(mover)
    asyncio.run(runner.http_client.aclose())

    assert mover.company_intro
    assert mover.main_products
    assert "公司主要产品" in mover.main_products or "公开信息显示" in mover.main_products or "相关" in mover.main_products
    assert mover.move_reason


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
