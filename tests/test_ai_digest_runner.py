import asyncio
from unittest.mock import Mock

import httpx

from src.digests.ai_runner import AIDigestRunner
from src.models import AIDigestConfig, SourcesConfig


def test_product_hunt_api_falls_back_to_global_top_posts_when_window_is_empty():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode()
        calls.append(payload)
        if '"postedAfter"' in payload:
            return httpx.Response(200, json={"data": {"posts": {"edges": []}}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "posts": {
                        "edges": [
                            {
                                "node": {
                                    "name": "Agent Studio",
                                    "tagline": "Build AI agent workflows",
                                    "description": "Build AI agent workflows",
                                    "url": "https://www.producthunt.com/posts/agent-studio",
                                    "votesCount": 321,
                                    "topics": {
                                        "edges": [
                                            {"node": {"name": "Developer Tools"}},
                                            {"node": {"name": "Artificial Intelligence"}},
                                        ]
                                    },
                                }
                            }
                        ]
                    }
                }
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    runner = AIDigestRunner(AIDigestConfig(enabled=True, top_n=5), SourcesConfig(), Mock(), client)

    projects = asyncio.run(runner._fetch_product_hunt_api(__import__("datetime").datetime(2026, 5, 11), "token"))
    asyncio.run(client.aclose())

    assert len(calls) == 2
    assert projects[0].name == "Agent Studio"
    assert projects[0].votes == 321
