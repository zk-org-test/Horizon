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
        "_search_public_context",
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
    assert "launch" in mover.main_products.lower() or "satellite" in mover.main_products.lower()
    assert mover.move_reason
