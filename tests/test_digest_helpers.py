"""Unit tests for digest helper logic."""

from __future__ import annotations

from datetime import datetime

from src.digests.ai_runner import classify_ai_category
from src.digests.finance_runner import get_previous_trading_day, pick_strongest_group


def test_previous_trading_day_skips_weekend():
    current = datetime(2026, 5, 11, 11, 0)  # Monday

    result = get_previous_trading_day(current)

    assert result.strftime("%Y-%m-%d") == "2026-05-08"


def test_pick_strongest_group_prefers_count_then_average_change():
    movers = [
        {"sector": "Technology", "change_pct": 8.0},
        {"sector": "Technology", "change_pct": 6.0},
        {"sector": "Energy", "change_pct": 9.0},
        {"sector": "Energy", "change_pct": 1.0},
        {"sector": "Healthcare", "change_pct": 12.0},
    ]

    result = pick_strongest_group(movers, "sector")

    assert result == "Technology"


def test_classify_ai_category_uses_topics_and_keywords():
    assert classify_ai_category(
        name="Browser Agent Cloud",
        description="An autonomous agent for browser tasks and workflows",
        topics=["Artificial Intelligence", "Developer Tools"],
    ) == "Agent"

    assert classify_ai_category(
        name="Vector Lake",
        description="Data infrastructure for embeddings and retrieval",
        topics=["Developer Tools", "Data"],
    ) == "Data"
