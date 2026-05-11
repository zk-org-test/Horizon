import asyncio
from unittest.mock import Mock

import httpx

from src.digests.ai_runner import AIDigestRunner, AIProject
from src.models import AIDigestConfig, SourcesConfig


def test_enrich_github_project_uses_repo_api_and_readme():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/bytedance/UI-TARS-desktop":
            return httpx.Response(
                200,
                json={
                    "description": "Open-source multimodal AI agent stack",
                    "topics": ["Artificial Intelligence", "Developer Tools"],
                    "homepage": "https://ui-tars.example.com",
                    "language": "Python",
                },
            )
        if request.url.path == "/repos/bytedance/UI-TARS-desktop/readme":
            return httpx.Response(
                200,
                text="# UI-TARS\n\nUI-TARS is a multimodal AI agent stack for desktop automation.",
            )
        return httpx.Response(404, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    runner = AIDigestRunner(AIDigestConfig(enabled=True, top_n=5), SourcesConfig(), Mock(), client)
    project = AIProject(
        source="github_trending",
        rank=1,
        name="bytedance/UI-TARS-desktop",
        description="",
        url="https://github.com/bytedance/UI-TARS-desktop",
        topics=[],
    )

    asyncio.run(runner._enrich_github_project(project))
    asyncio.run(client.aclose())

    assert "multimodal" in project.description.lower()
    assert "Artificial Intelligence" in project.topics
    assert project.research_context
