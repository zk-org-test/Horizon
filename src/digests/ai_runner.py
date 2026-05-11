"""AI digest data collection and rendering."""

from __future__ import annotations

import os
import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Optional

import feedparser
import httpx
from ddgs import DDGS
from bs4 import BeautifulSoup

from ..ai.client import AIClient
from ..ai.utils import parse_json_response
from ..models import AIDigestConfig, SourcesConfig
from .summarizers import AiDigestSummary, AiSummarizer


AI_CATEGORY_ZH = {
    "Agent": "智能体",
    "Data": "数据",
    "DevTool": "开发工具",
    "Infra": "模型基础设施",
    "Design": "设计创作",
    "Productivity": "效率办公",
    "Open Source": "开源工具",
}

AI_TOPIC_ZH = {
    "Artificial Intelligence": "人工智能",
    "Developer Tools": "开发工具",
    "Data": "数据",
    "Design": "设计创作",
    "Open Source": "开源",
    "Productivity": "效率办公",
    "Machine Learning": "机器学习",
    "Automation": "自动化",
}

AI_TOPIC_TOKEN_ZH = {
    "agent": "智能体",
    "agents": "智能体",
    "ai": "人工智能",
    "llm": "大模型",
    "rag": "检索增强",
    "browser": "浏览器自动化",
    "automation": "自动化",
    "autonomous": "自主执行",
    "coding": "编程",
    "code": "编程",
    "developer": "开发工具",
    "tools": "开发工具",
    "workflow": "工作流",
    "security": "安全",
    "privacy": "隐私",
    "inference": "推理",
    "server": "服务端",
    "multimodal": "多模态",
    "image": "图像",
    "video": "视频",
    "audio": "音频",
    "benchmark": "评测",
    "eval": "评测",
    "evaluation": "评测",
    "trading": "交易",
    "finance": "金融",
    "email": "邮件",
    "calendar": "日历",
    "document": "文档",
    "docs": "文档",
    "design": "设计",
    "ui": "界面",
    "browseruse": "浏览器自动化",
    "claude": "Claude生态",
    "anthropic": "Anthropic生态",
    "apple": "苹果生态",
    "silicon": "苹果芯片",
    "data": "数据",
    "gateway": "网关",
    "infra": "基础设施",
}


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
    summary_zh: Optional[str] = None
    name_zh: Optional[str] = None
    why_cn: Optional[str] = None
    research_context: list[str] | None = None
    topics_zh: list[str] | None = None

    def to_line(self) -> str:
        display_name = self.name if not self.name_zh else f"{self.name}（{self.name_zh}）"
        zh_topics = self.topics_zh or self._fallback_topics()
        topic_part = f" | 主题：{', '.join(zh_topics)}" if zh_topics else ""
        metric = f" | 热度：{self.votes}" if self.votes is not None else ""
        summary = self.summary_zh or self.description
        return f"- #{self.rank} [{display_name}]({self.url})：{summary} | 分类：{self.category_zh}{topic_part}{metric}"

    @property
    def category_zh(self) -> str:
        return AI_CATEGORY_ZH.get(self.category, self.category)

    def _fallback_topics(self) -> list[str]:
        return AIDigestRunner._fallback_topics_zh(self)


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
        self.search_semaphore = asyncio.Semaphore(6)
        self.enable_public_search = os.getenv("HORIZON_ENABLE_PUBLIC_SEARCH", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    async def run(self, now: Optional[datetime] = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        github_items = await self._fetch_github_trending()
        product_hunt_items = await self._fetch_product_hunt(current)
        await self._enrich_projects(github_items, product_hunt_items)
        await self._localize_projects(github_items + product_hunt_items)

        all_items = github_items + product_hunt_items
        counts = Counter(item.category for item in all_items)
        category_lines = [f"- {AI_CATEGORY_ZH.get(name, name)}：{count} 个项目" for name, count in counts.most_common()]

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

    async def _enrich_projects(
        self,
        github_items: list[AIProject],
        product_hunt_items: list[AIProject],
    ) -> None:
        await asyncio.gather(
            *(self._enrich_github_project(project) for project in github_items),
            *(self._enrich_product_hunt_project(project) for project in product_hunt_items),
        )

    async def _enrich_github_project(self, project: AIProject) -> None:
        owner_repo = self._extract_github_repo(project)
        if owner_repo:
            repo_info, readme = await asyncio.gather(
                self._fetch_github_repo_info(owner_repo),
                self._fetch_github_readme(owner_repo),
            )
            if repo_info:
                description = str(repo_info.get("description") or "").strip()
                if description:
                    project.description = description
                topics = [str(topic) for topic in repo_info.get("topics") or [] if topic]
                if topics:
                    project.topics = list(dict.fromkeys(topics + project.topics))
                homepage = str(repo_info.get("homepage") or "").strip()
                if homepage:
                    page_summary = await self._fetch_page_summary(homepage)
                    if page_summary:
                        project.research_context = (project.research_context or []) + [page_summary]
            if readme:
                project.research_context = (project.research_context or []) + [readme]

        if self.enable_public_search and self._should_use_public_search(project):
            search_context = await self._get_public_context(project.name, "github")
            if search_context:
                project.research_context = (project.research_context or []) + search_context

        project.topics = list(dict.fromkeys(project.topics))
        project.category = classify_ai_category(
            project.name,
            " ".join([project.description] + (project.research_context or [])),
            project.topics,
        )

    async def _enrich_product_hunt_project(self, project: AIProject) -> None:
        page_summary = await self._fetch_page_summary(project.url)
        if page_summary:
            project.research_context = (project.research_context or []) + [page_summary]
        if self.enable_public_search and self._should_use_public_search(project):
            search_context = await self._get_public_context(project.name, "product_hunt")
            if search_context:
                project.research_context = (project.research_context or []) + search_context
        project.category = classify_ai_category(
            project.name,
            " ".join([project.description] + (project.research_context or [])),
            project.topics,
        )

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
            notable.append(f"{project.name}：{AI_CATEGORY_ZH.get(project.category, project.category)}方向热度较高，值得继续观察。")
        return {
            "headline": f"今天 AI 榜单最强主线集中在 {AI_CATEGORY_ZH.get(dominant, dominant)}方向。",
            "notable_projects": notable,
            "trend_outlook": f"{AI_CATEGORY_ZH.get(dominant, dominant)}相关项目在 GitHub Trending 和 Product Hunt 同时出现，短期内仍会继续升温。",
        }

    def _find_feed_url(self, feed_name: str) -> Optional[str]:
        for source in self.sources.rss:
            if source.name == feed_name and source.enabled:
                return str(source.url)
        return None

    @staticmethod
    def _html_to_text(value: str) -> str:
        return unescape(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))

    async def _localize_projects(self, projects: list[AIProject]) -> None:
        if not projects:
            return

        zh_to_en = {value: key for key, value in AI_CATEGORY_ZH.items()}
        for start in range(0, len(projects), 8):
            batch = projects[start:start + 8]
            payload = [
                {
                    "name": project.name,
                    "source": project.source,
                    "category": project.category,
                    "description": project.description,
                    "topics": [AI_TOPIC_ZH.get(topic, topic) for topic in project.topics[:3]],
                    "research_context": (project.research_context or [])[:4],
                }
                for project in batch
            ]
            system = (
                "你是一名双语 AI 产品分析师。请把项目摘要、亮点、主题和分类全部转成自然中文，只返回 JSON。"
                "输出必须以中文为主，保留仓库名或产品名原文作为标识，不要直接复制长段英文、页面标题或搜索结果标题。"
            )
            user = (
                '返回 JSON：{"items":[{"name":"","name_zh":"","summary_zh":"","why_cn":"","category_zh":"","topics_zh":[]}]}\n'
                f"项目列表：{payload}"
            )
            try:
                response = await asyncio.wait_for(
                    self.ai_client.complete(system=system, user=user, max_tokens=2600),
                    timeout=45,
                )
                result = parse_json_response(response) or {}
            except Exception:
                result = {}

            localized_map = {str(item.get("name")): item for item in result.get("items", []) if item.get("name")}
            for project in batch:
                item = localized_map.get(project.name, {})
                project.name_zh = str(item.get("name_zh") or "").strip() or None
                project.summary_zh = str(item.get("summary_zh") or "").strip() or self._fallback_project_summary(project)
                project.why_cn = str(item.get("why_cn") or "").strip() or None
                category_zh = str(item.get("category_zh") or "").strip()
                if category_zh:
                    project.category = zh_to_en.get(category_zh, project.category)
                topics_zh = item.get("topics_zh")
                if isinstance(topics_zh, list) and topics_zh:
                    project.topics_zh = [
                        self._topic_to_chinese(str(topic).strip(), project.category)
                        for topic in topics_zh
                        if str(topic).strip()
                    ]
                else:
                    project.topics_zh = self._fallback_topics_zh(project)
                project.summary_zh = self._normalize_chinese_project_text(
                    project.summary_zh,
                    fallback=self._fallback_project_summary(project),
                )
                project.why_cn = self._normalize_chinese_project_text(
                    project.why_cn or "",
                    fallback=f"{project.name} 所在的{project.category_zh}方向近期热度较高。",
                )

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

    @staticmethod
    def _extract_github_repo(project: AIProject) -> Optional[str]:
        if "/" in project.name and project.name.count("/") == 1:
            return project.name
        if "github.com/" in project.url:
            return project.url.split("github.com/", 1)[1].strip("/").split("/issues", 1)[0]
        return None

    async def _fetch_github_repo_info(self, owner_repo: str) -> dict[str, Any]:
        headers = {"Accept": "application/vnd.github+json"}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = await self.http_client.get(
                f"https://api.github.com/repos/{owner_repo}",
                headers=headers,
                timeout=20.0,
            )
        except httpx.HTTPError:
            return {}
        if response.status_code != 200:
            return {}
        return response.json()

    async def _fetch_github_readme(self, owner_repo: str) -> Optional[str]:
        headers = {"Accept": "application/vnd.github.raw+json"}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = await self.http_client.get(
                f"https://api.github.com/repos/{owner_repo}/readme",
                headers=headers,
                timeout=20.0,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        text = response.text.strip()
        return self._html_to_text(text)[:800] if text else None

    async def _fetch_page_summary(self, url: str) -> Optional[str]:
        if not url:
            return None
        try:
            response = await self.http_client.get(url, timeout=15.0, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        meta = (
            soup.find("meta", attrs={"name": "description"})
            or soup.find("meta", attrs={"property": "og:description"})
        )
        desc = str(meta.get("content") or "").strip() if meta else ""
        parts = [part for part in [title, desc] if part]
        return " - ".join(parts)[:280] if parts else None

    def _should_use_public_search(self, project: AIProject) -> bool:
        if project.source == "github_trending" and project.research_context and project.description:
            return False
        return not project.research_context

    @staticmethod
    def _search_public_context(name: str, source: str) -> list[str]:
        import sys

        query = f"{name} {'github project latest summary' if source == 'github' else 'product hunt ai product summary'}"
        snippets: list[str] = []
        stderr = sys.stderr
        sys.stderr = open(os.devnull, "w")
        try:
            ddgs = DDGS()
            results = ddgs.text(query, max_results=3)
            for item in results or []:
                title = str(item.get("title") or "").strip()
                body = str(item.get("body") or "").strip()
                line = " - ".join(part for part in [title, body] if part)
                if line:
                    snippets.append(line[:280])
        except Exception:
            return []
        finally:
            sys.stderr.close()
            sys.stderr = stderr
        return snippets[:3]

    async def _get_public_context(self, name: str, source: str) -> list[str]:
        async with self.search_semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._search_public_context, name, source),
                    timeout=12,
                )
            except Exception:
                return []

    @staticmethod
    def _fallback_project_summary(project: AIProject) -> str:
        topic_text = "、".join(AIDigestRunner._fallback_topics_zh(project)[:3]) or "AI工具"
        category = AI_CATEGORY_ZH.get(project.category, project.category)
        source = "GitHub Trending" if project.source == "github_trending" else "Product Hunt"
        return f"{project.name} 是一个围绕{topic_text}的{category}项目，近期在 {source} 榜单中的关注度较高。"

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        import re

        return bool(re.search(r"[\u4e00-\u9fff]", text or ""))

    @classmethod
    def _needs_project_localization(cls, project: AIProject) -> bool:
        summary = (project.summary_zh or "").strip()
        if not summary:
            return True
        if not cls._contains_chinese(summary):
            return True
        if any(not cls._contains_chinese(topic) for topic in (project.topics_zh or [])):
            return True
        return False

    @classmethod
    def _normalize_chinese_project_text(cls, text: str, fallback: str) -> str:
        normalized = (text or "").strip()
        if not normalized or not cls._contains_chinese(normalized):
            fallback_text = (fallback or "").strip()
            if cls._contains_chinese(fallback_text):
                return fallback_text
            return "该项目围绕 AI 工具链与工作流场景展开，近期在榜单中体现出较高关注度。"
        normalized = re.sub(r"Artificial Intelligence\s*-\s*Product Hunt.*$", "人工智能相关方向近期关注度较高。", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _fallback_topics_zh(project: AIProject) -> list[str]:
        mapped = [
            AIDigestRunner._topic_to_chinese(topic, project.category)
            for topic in project.topics[:3]
        ]
        deduped = list(dict.fromkeys(topic for topic in mapped if topic))
        return deduped or [AI_CATEGORY_ZH.get(project.category, "AI工具")]

    @staticmethod
    def _topic_to_chinese(topic: str, category: str) -> str:
        normalized = (topic or "").strip()
        if not normalized:
            return AI_CATEGORY_ZH.get(category, "AI工具")
        if normalized in AI_TOPIC_ZH:
            return AI_TOPIC_ZH[normalized]
        if re.search(r"[\u4e00-\u9fff]", normalized):
            return normalized

        compact = normalized.lower().replace("_", "-").replace("/", "-")
        if compact in AI_TOPIC_TOKEN_ZH:
            return AI_TOPIC_TOKEN_ZH[compact]

        pieces = [piece for piece in re.split(r"[^a-z0-9]+", compact) if piece]
        translated = []
        for piece in pieces:
            mapped = AI_TOPIC_TOKEN_ZH.get(piece)
            if mapped and mapped not in translated:
                translated.append(mapped)
        if translated:
            return " / ".join(translated[:2])
        return AI_CATEGORY_ZH.get(category, "AI工具")
