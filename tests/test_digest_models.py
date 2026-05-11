"""Unit tests for dual-digest configuration models."""

from __future__ import annotations

import json

from src.storage.manager import StorageManager


def test_load_config_supports_finance_and_ai_digests(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_path = data_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {
                    "provider": "openai",
                    "model": "gpt-5.2-chat-latest",
                    "api_key_env": "OPENAI_API_KEY",
                },
                "sources": {},
                "filtering": {
                    "ai_score_threshold": 7.0,
                    "time_window_hours": 24,
                },
                "digests": {
                    "finance": {
                        "enabled": True,
                        "language": "zh",
                        "top_n": 20,
                        "webhook_title": "金融日报",
                    },
                    "ai": {
                        "enabled": True,
                        "language": "zh",
                        "top_n": 20,
                        "webhook_title": "AI 日报",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = StorageManager(str(data_dir)).load_config()

    assert config.digests is not None
    assert config.digests.finance.enabled is True
    assert config.digests.finance.top_n == 20
    assert config.digests.finance.webhook_title == "金融日报"
    assert config.digests.ai.enabled is True
    assert config.digests.ai.webhook_title == "AI 日报"
