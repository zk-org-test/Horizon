"""AI digest data collection and rendering."""

from __future__ import annotations

import os
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from ..models import AIDigestConfig, SourcesConfig
from .summarizers import AiDigestSummary, AiSummarizer


def classify_ai_category(name: str, description: str, topics: list[str]) -> str:
    """Map AI products and repos into a digest-friendly category."""
    text = " ".join([name, description, " ".join(topics)]).lower()
    if any(keyword in text for keyword in ["agent", "browser", "workflow", "automation", "copilot"]):
        return "Agent"
    if any(keyword in text for keyword in ["vector", "retrieval", "dataset", "data", "etl", "lake"]):
        return "Data"
    if any(keyword in text for keyword in ["devtool", "developer", "sdk", "cli", "framework", "coding"]):
        return "DevTool"
    if any(keyword in text for keyword in ["model", "llm", "multimodal", "inference", "training"]):
        return "Infra"
    if any(keyword in text for keyword in ["design", "image", "video", "creative", "ui"]):
        return "Design"
    if any(keyword in text for keyword in ["productivity", "meeting", "calendar", "document", "email"]):
        return "Productivity"
    return "Open Source"


@dataclass
class AIProject:
    source: str
    rank: int
    name: str
    description: str
    url: str
    topics: list[str]
    votes: Optional[int] = None
    category: str = "Open Source"

    def to_line(self) -> str:
        topic_part = f" | 主题：{', '.join(self.topics[:3])}" if self.topics else ""
        metric = f" | 热度：{self.votes}" if self.votes is not None else ""
        return f"- #{self.rank} [{self.name}]({self.url})：{self.description}{topic_part}{metric}"


class AIDigestRunner:
    """Build the AI daily digest."""

    def __init__(
        self,
        config: AIDigestConfig,
        sources: SourcesConfig,
        ai_client: AIClient,
        http_client: httpx.AsyncClient,
    ):
        self.config = config
        self.sources = sources
        self.ai_client = ai_client
        self.http_client = http_client

    async def run(self, now: Optional[datetime] = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        github_items = await self._fetch_github_trending()
        product_hunt_items = await self._fetch_product_hunt(current)

        all_items = github_items + product_hunt_items
        counts = Counter(item.category for item in all_items)
        category_lines = [f"- {name}: {count} 个项目" for name, count in counts.most_common()]

        insights = await self._generate_ai_insights(github_items, product_hunt_items, counts)
        summary = AiDigestSummary(
            date=current.strftime("%Y-%m-%d"),
            headline=insights["headline"],
            github_trending=[item.to_line() for item in github_items],
            product_hunt=[item.to_line() for item in product_hunt_items],
            category_breakdown=category_lines,
            notable_projects=insights["notable_projects"],
            trend_outlook=insights["trend_outlook"],
        )
        markdown = AiSummarizer().render(summary)
        return {
            "kind": "ai",
            "title": f"{self.config.webhook_title} | {summary.date}",
            "summary": markdown,
            "date": summary.date,
            "lang": self.config.language,
        }

    async def _fetch_github_trending(self) -> list[AIProject]:
        feed_url = self._find_feed_url(self.config.github_feed_name)
        if not feed_url:
            raise RuntimeError(f"Missing RSS feed for {self.config.github_feed_name}")

        feed = await asyncio.to_thread(feedparser.parse, feed_url)
        projects: list[AIProject] = []
        for index, entry in enumerate(feed.entries[: self.config.top_n], start=1):
            description = self._html_to_text(entry.get("summary") or entry.get("description") or "")
            project = AIProject(
                source="github_trending",
                rank=index,
                name=str(entry.get("title") or "Unknown"),
                description=description[:240],
                url=str(entry.get("link") or ""),
                topics=self._infer_topics_from_repo(description),
            )
            project.category = classify_ai_category(project.name, project.description, project.topics)
            projects.append(project)
        return projects

    async def _fetch_product_hunt(self, current: datetime) -> list[AIProject]:
        token = os.getenv(self.config.product_hunt_token_env)
        if token:
            projects = await self._fetch_product_hunt_api(current, token)
            if projects:
                return projects
        return await self._fetch_product_hunt_feed()

    async def _fetch_product_hunt_api(self, current: datetime, token: str) -> list[AIProject]:
        posted_after = (current - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        posted_before = current.replace(hour=0, minute=0, second=0, microsecond=0)
        query = """
        query Posts($first: Int!, $postedAfter: DateTime, $postedBefore: DateTime) {
          posts(first: $first, order: RANKING, postedAfter: $postedAfter, postedBefore: $postedBefore) {
            edges {
              node {
                name
                tagline
                description
                url
                votesCount
                topics {
                  edges {
                    node {
                      name
                    }
                  }
                }
              }
            }
          }
        }
        """
        edges = await self._query_product_hunt_edges(
            token,
            query,
            {
                "first": self.config.top_n,
                "postedAfter": posted_after.isoformat(),
                "postedBefore": posted_before.isoformat(),
            },
        )
        if not edges:
            fallback_query = """
            query Posts($first: Int!) {
              posts(first: $first, order: RANKING) {
                edges {
                  node {
                    name
                    tagline
                    description
                    url
                    votesCount
                    topics {
                      edges {
                        node {
                          name
                        }
                      }
                    }
                  }
                }
              }
            }
            """
            edges = await self._query_product_hunt_edges(
                token,
                fallback_query,
                {"first": self.config.top_n},
            )

        projects: list[AIProject] = []
        for index, edge in enumerate(edges, start=1):
            node = edge.get("node") or {}
            topics = [
                str(item.get("node", {}).get("name"))
                for item in (node.get("topics", {}).get("edges") or [])
                if item.get("node", {}).get("name")
            ]
            description = str(node.get("tagline") or node.get("description") or "")
            project = AIProject(
                source="product_hunt",
                rank=index,
                name=str(node.get("name") or "Unknown"),
                description=description,
                url=str(node.get("url") or ""),
                topics=topics,
                votes=node.get("votesCount"),
            )
            project.category = classify_ai_category(project.name, project.description, project.topics)
            projects.append(project)
        return projects

    async def _query_product_hunt_edges(
        self,
        token: str,
        query: str,
        variables: dict[str, Any],
    ) -> list[dict[str, Any]]:
        response = await self.http_client.post(
            "https://api.producthunt.com/v2/api/graphql",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": variables,
            },
            timeout=30.0,
        )
        if response.status_code != 200:
            return []

        payload = response.json()
        return (((payload.get("data") or {}).get("posts") or {}).get("edges")) or []

    async def _fetch_product_hunt_feed(self) -> list[AIProject]:
        feed_url = self._find_feed_url(self.config.product_hunt_feed_name)
        if not feed_url:
            raise RuntimeError(f"Missing RSS feed for {self.config.product_hunt_feed_name}")

        feed = await asyncio.to_thread(feedparser.parse, feed_url)
        projects: list[AIProject] = []
        for index, entry in enumerate(feed.entries[: self.config.top_n], start=1):
            description = self._html_to_text(entry.get("summary") or entry.get("description") or "")
            project = AIProject(
                source="product_hunt",
                rank=index,
                name=str(entry.get("title") or "Unknown"),
                description=description[:240],
                url=str(entry.get("link") or ""),
                topics=self._infer_topics_from_repo(description),
            )
            project.category = classify_ai_category(project.name, project.description, project.topics)
            projects.append(project)
        return projects

    async def _generate_ai_insights(
        self,
        github_items: list[AIProject],
        product_hunt_items: list[AIProject],
        counts: Counter[str],
    ) -> dict[str, Any]:
        payload = {
            "github_top": [project.__dict__ for project in github_items[:8]],
            "product_hunt_top": [project.__dict__ for project in product_hunt_items[:8]],
            "category_counts": dict(counts),
        }
        system = "你是一名 AI 产业观察者。请只返回 JSON。"
        user = (
            "请用中文输出以下 JSON："
            '{"headline":"一句话总览","notable_projects":["项目与原因1","项目与原因2","项目与原因3"],'
            '"trend_outlook":"后续趋势判断"}\n\n'
            f"数据：{payload}"
        )
        try:
            response = await asyncio.wait_for(
                self.ai_client.complete(system=system, user=user, max_tokens=1200),
                timeout=45,
            )
            result = parse_json_response(response)
        except Exception:
            result = None

        fallback = self._fallback_ai_insights(github_items, product_hunt_items, counts)
        if not result:
            return fallback

        return {
            "headline": str(result.get("headline") or fallback["headline"]),
            "notable_projects": [str(item) for item in result.get("notable_projects") or fallback["notable_projects"]],
            "trend_outlook": str(result.get("trend_outlook") or fallback["trend_outlook"]),
        }

    @staticmethod
    def _fallback_ai_insights(
        github_items: list[AIProject],
        product_hunt_items: list[AIProject],
        counts: Counter[str],
    ) -> dict[str, Any]:
        dominant = counts.most_common(1)[0][0] if counts else "Agent"
        notable = []
        for project in (github_items + product_hunt_items)[:5]:
            notable.append(f"{project.name}：{project.category} 方向热度较高，值得继续观察。")
        return {
            "headline": f"今天 AI 榜单最强主线集中在 {dominant} 方向。",
            "notable_projects": notable,
            "trend_outlook": f"{dominant} 相关项目在 GitHub Trending 和 Product Hunt 同时出现，短期内仍会继续升温。",
        }

    def _find_feed_url(self, feed_name: str) -> Optional[str]:
        for source in self.sources.rss:
            if source.name == feed_name and source.enabled:
                return str(source.url)
        return None

    @staticmethod
    def _html_to_text(value: str) -> str:
        return unescape(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))

    @staticmethod
    def _infer_topics_from_repo(text: str) -> list[str]:
        keywords = []
        lowered = text.lower()
        for label, hints in {
            "Artificial Intelligence": ["ai", "llm", "model", "agent", "inference"],
            "Developer Tools": ["sdk", "developer", "coding", "cli", "framework"],
            "Data": ["data", "vector", "retrieval", "database", "etl"],
            "Design": ["design", "image", "video", "creative"],
        }.items():
            if any(hint in lowered for hint in hints):
                keywords.append(label)
        return keywords
