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


def test_needs_project_localization_flags_english_summary():
    project = AIProject(
        source="github_trending",
        rank=1,
        name="demo/repo",
        description="",
        url="https://github.com/demo/repo",
        topics=["Artificial Intelligence"],
        summary_zh="This is still English.",
    )

    assert AIDigestRunner._needs_project_localization(project)


def test_fallback_project_summary_returns_chinese_without_raw_english_context():
    project = AIProject(
        source="product_hunt",
        rank=1,
        name="Glowix",
        description="",
        url="https://www.producthunt.com/products/glowix",
        topics=["Artificial Intelligence", "Design"],
        category="Design",
        research_context=["Artificial Intelligence - Product Hunt - Artificial intelligence powers products..."],
    )

    summary = AIDigestRunner._fallback_project_summary(project)

    assert "Artificial Intelligence - Product Hunt" not in summary
    assert "围绕" in summary
    assert "关注度较高" in summary


def test_normalize_chinese_project_text_replaces_product_hunt_boilerplate():
    text = "该项目聚焦AI工具，当前最值得关注的是：Artificial Intelligence - Product Hunt - Artificial intelligence powers products。"

    normalized = AIDigestRunner._normalize_chinese_project_text(text, fallback="这是中文兜底。")

    assert "Product Hunt" not in normalized
    assert "人工智能相关方向近期关注度较高" in normalized


def test_fallback_topics_zh_translates_english_repo_tags():
    project = AIProject(
        source="github_trending",
        rank=1,
        name="demo/repo",
        description="",
        url="https://github.com/demo/repo",
        topics=["browser-use", "ai-agents", "coding"],
        category="Agent",
    )

    topics = AIDigestRunner._fallback_topics_zh(project)

    assert "浏览器自动化" in topics
    assert any("智能体" in topic or "人工智能" in topic for topic in topics)
