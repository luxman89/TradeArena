"""Paperclip API client for creating issues from Discord bug reports."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger("tradearena.bot.paperclip")


@dataclass
class PaperclipIssue:
    """Represents a created Paperclip issue."""

    id: str
    identifier: str
    title: str


class PaperclipClient:
    """Lightweight async client for the Paperclip issue-creation API."""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        company_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.api_url = (api_url or os.getenv("PAPERCLIP_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("PAPERCLIP_API_KEY", "")
        self.company_id = company_id or os.getenv("PAPERCLIP_COMPANY_ID", "")
        self.project_id = project_id or os.getenv("PAPERCLIP_PROJECT_ID", "")

    @property
    def configured(self) -> bool:
        """Return True if minimum Paperclip credentials are set."""
        return bool(self.api_url and self.api_key and self.company_id)

    async def create_issue(
        self,
        title: str,
        description: str,
        priority: str = "medium",
    ) -> PaperclipIssue | None:
        """Create a Paperclip issue. Returns the created issue or None on failure."""
        if not self.configured:
            log.warning("Paperclip not configured — skipping issue creation")
            return None

        payload: dict = {
            "title": title,
            "description": description,
            "priority": priority,
            "status": "todo",
        }
        if self.project_id:
            payload["projectId"] = self.project_id

        url = f"{self.api_url}/api/companies/{self.company_id}/issues"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                issue = PaperclipIssue(
                    id=data["id"],
                    identifier=data["identifier"],
                    title=data["title"],
                )
                log.info("Created Paperclip issue %s: %s", issue.identifier, issue.title)
                return issue
        except httpx.HTTPStatusError as exc:
            log.error(
                "Paperclip API error %s: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
        except Exception:
            log.exception("Failed to create Paperclip issue")
        return None
