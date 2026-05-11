"""Digest-specific orchestration for finance and AI daily briefings."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from rich.console import Console

from ..ai.client import create_ai_client
from ..models import Config
from ..services.webhook import WebhookNotifier
from ..storage.manager import StorageManager
from .ai_runner import AIDigestRunner
from .finance_runner import FinanceDigestRunner


class DigestOrchestrator:
    """Run the finance + AI digest pipeline."""

    def __init__(self, config: Config, storage: StorageManager):
        self.config = config
        self.storage = storage
        self.console = Console()
        self.webhook_notifier = (
            WebhookNotifier(config.webhook, console=self.console)
            if config.webhook and config.webhook.enabled
            else None
        )

    async def run(self, dry_run: bool = False) -> list[dict]:
        if not self.config.digests:
            raise ValueError("Digest mode requested but config.digests is missing.")

        self.console.print("[bold cyan]🧭 Horizon Digests - Starting dual daily run...[/bold cyan]\n")

        ai_client = create_ai_client(self.config.ai)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http_client:
            messages: list[dict] = []

            if self.config.digests.finance.enabled:
                self.console.print("💹 Building finance digest...")
                finance = FinanceDigestRunner(self.config.digests.finance, ai_client, http_client)
                messages.append(await finance.run())

            if self.config.digests.ai.enabled:
                self.console.print("🤖 Building AI digest...")
                ai = AIDigestRunner(self.config.digests.ai, self.config.sources, ai_client, http_client)
                messages.append(await ai.run())

        self._save_messages(messages)

        if dry_run:
            self.console.print("[yellow]Dry-run enabled; not sending webhook.[/yellow]\n")
            if self.webhook_notifier:
                previews = [self.webhook_notifier.build_preview(message) for message in messages]
                self.console.print(json.dumps(previews, ensure_ascii=False, indent=2))
            else:
                self.console.print(json.dumps(messages, ensure_ascii=False, indent=2))
            return messages

        if self.webhook_notifier and messages:
            self.console.print("🔔 Sending digest webhook notifications...")
            await self.webhook_notifier.send_digest_messages(messages)

        self.console.print("[bold green]✅ Digest pipeline completed successfully![/bold green]")
        return messages

    def _save_messages(self, messages: list[dict]) -> None:
        for message in messages:
            kind = str(message["kind"])
            date = str(message["date"])
            lang = str(message.get("lang") or "zh")
            path = self.storage.save_digest_summary(kind, date, message["summary"], lang)
            self.console.print(f"💾 Saved {kind} digest to: {path}")
            self._copy_to_docs(kind, date, lang, message["title"], message["summary"])

    def _copy_to_docs(self, kind: str, date: str, lang: str, title: str, summary: str) -> None:
        posts_dir = Path("docs/_posts")
        posts_dir.mkdir(parents=True, exist_ok=True)
        dest_path = posts_dir / f"{date}-{kind}-digest-{lang}.md"
        front_matter = (
            "---\n"
            "layout: default\n"
            f'title: "{title}"\n'
            f"date: {date}\n"
            f"lang: {lang}\n"
            f"kind: {kind}\n"
            "---\n\n"
        )
        body = summary
        first_line = body.strip().split("\n")[0]
        if first_line.startswith("# "):
            parts = body.split("\n", 1)
            body = parts[1].strip() if len(parts) > 1 else body

        with open(dest_path, "w", encoding="utf-8") as handle:
            handle.write(front_matter + body)
