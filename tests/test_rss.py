import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from src.models import RSSSourceConfig, SourcesConfig
from src.scrapers.rss import RSSScraper


def test_rss_feed_level_updated_is_used_when_entries_lack_timestamps():
    feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Example feed</title>
      <updated>2026-05-10T08:00:00Z</updated>
      <entry>
        <id>tag:example.com,2026:1</id>
        <title>GitHub Trending Example</title>
        <link href="https://github.com/example/repo" />
        <content type="html">Example content</content>
      </entry>
    </feed>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=feed_xml, headers={"Content-Type": "application/atom+xml"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    scraper = RSSScraper(
        [
            RSSSourceConfig(
                name="GitHub Trending - Daily",
                url="https://example.com/feed.xml",
                enabled=True,
                category="github-trending",
            )
        ],
        client,
    )

    since = datetime(2026, 5, 10, 7, 0, tzinfo=timezone.utc)
    items = asyncio.run(scraper.fetch(since))
    asyncio.run(client.aclose())

    assert len(items) == 1
    assert items[0].title == "GitHub Trending Example"
    assert items[0].published_at == datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc)


def test_telegram_source_is_disabled_by_default():
    sources = SourcesConfig()

    assert sources.telegram.enabled is False
    assert sources.telegram.channels == []
