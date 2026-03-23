"""Tests for the Discord bot — bug report escalation to Paperclip issues."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.discord_bot.bot import (
    _build_issue_description,
    _extract_bug_title,
    _handle_bug_report,
)
from services.discord_bot.paperclip import PaperclipClient, PaperclipIssue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    content: str,
    author_name: str = "TestUser",
    channel_name: str = "bug-reports",
    has_reference: bool = False,
) -> MagicMock:
    """Create a mock Discord Message."""
    msg = MagicMock()
    msg.content = content
    msg.author = MagicMock()
    msg.author.display_name = author_name
    msg.author.id = 12345
    msg.channel = MagicMock()
    msg.channel.name = channel_name
    msg.guild = MagicMock()
    msg.guild.name = "TradeArena"
    msg.jump_url = "https://discord.com/channels/123/456/789"
    msg.reference = MagicMock() if has_reference else None
    msg.add_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.delete = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# _extract_bug_title
# ---------------------------------------------------------------------------


class TestExtractBugTitle:
    def test_first_line_used(self):
        content = "Signal submission returns 500\nSteps to reproduce..."
        assert _extract_bug_title(content) == "Signal submission returns 500"

    def test_strips_markdown_heading(self):
        content = "## Signal submission returns 500\nDetails here"
        assert _extract_bug_title(content) == "Signal submission returns 500"

    def test_truncates_long_lines(self):
        content = "A" * 150
        title = _extract_bug_title(content)
        assert len(title) <= 104  # 100 + "..."
        assert title.endswith("...")

    def test_skips_short_lines(self):
        content = "Bug\n\nSignal submission returns 500 when confidence is 1.0"
        assert "Signal submission" in _extract_bug_title(content)

    def test_fallback_for_empty(self):
        assert _extract_bug_title("short") == "Bug report from Discord"


# ---------------------------------------------------------------------------
# _build_issue_description
# ---------------------------------------------------------------------------


class TestBuildIssueDescription:
    def test_includes_author(self):
        msg = _make_message("Some bug content", author_name="alice")
        desc = _build_issue_description(msg)
        assert "alice" in desc
        assert "(Discord)" in desc

    def test_includes_jump_url(self):
        msg = _make_message("Some bug content")
        desc = _build_issue_description(msg)
        assert "discord.com/channels" in desc

    def test_includes_content(self):
        msg = _make_message("Steps to reproduce: call /submit\nExpected: 200\nActual: 500")
        desc = _build_issue_description(msg)
        assert "Steps to reproduce" in desc
        assert "Actual: 500" in desc


# ---------------------------------------------------------------------------
# _handle_bug_report
# ---------------------------------------------------------------------------


class TestHandleBugReport:
    @pytest.mark.asyncio
    async def test_ignores_short_messages(self):
        msg = _make_message("short")
        await _handle_bug_report(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_replies(self):
        msg = _make_message(
            "Steps to reproduce the error with expected behavior",
            has_reference=True,
        )
        await _handle_bug_report(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompts_template_when_insufficient_detail(self):
        msg = _make_message("The leaderboard page is broken and I don't like it")
        await _handle_bug_report(msg)
        msg.reply.assert_called_once()
        reply_text = msg.reply.call_args[0][0]
        assert "Steps to reproduce" in reply_text
        msg.add_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_acknowledges_detailed_report_without_paperclip(self):
        """When Paperclip is not configured, just acknowledge."""
        msg = _make_message(
            "Steps to reproduce:\n1. Call /submit\n"
            "Expected behavior: 200 OK\n"
            "Actual behavior: 500 error"
        )
        with patch("services.discord_bot.bot._paperclip") as mock_pc:
            mock_pc.configured = False
            await _handle_bug_report(msg)

        msg.add_reaction.assert_any_call("✅")
        msg.reply.assert_called_once()
        reply_text = msg.reply.call_args[0][0]
        assert "engineering team" in reply_text

    @pytest.mark.asyncio
    async def test_escalates_to_paperclip_when_configured(self):
        """When Paperclip is configured, create an issue and reply with identifier."""
        msg = _make_message(
            "Steps to reproduce:\n1. Call /submit\n"
            "Expected behavior: 200 OK\n"
            "Actual behavior: 500 error"
        )
        fake_issue = PaperclipIssue(id="abc-123", identifier="TRAA-99", title="test")
        with patch("services.discord_bot.bot._paperclip") as mock_pc:
            mock_pc.configured = True
            mock_pc.create_issue = AsyncMock(return_value=fake_issue)
            await _handle_bug_report(msg)

        msg.add_reaction.assert_any_call("✅")
        msg.add_reaction.assert_any_call("🎫")
        msg.reply.assert_called_once()
        reply_text = msg.reply.call_args[0][0]
        assert "TRAA-99" in reply_text

    @pytest.mark.asyncio
    async def test_falls_back_when_paperclip_creation_fails(self):
        """When Paperclip issue creation fails, fall back to acknowledgement."""
        msg = _make_message(
            "Error traceback when expected behavior is submit\nSteps to reproduce the actual issue"
        )
        with patch("services.discord_bot.bot._paperclip") as mock_pc:
            mock_pc.configured = True
            mock_pc.create_issue = AsyncMock(return_value=None)
            await _handle_bug_report(msg)

        msg.add_reaction.assert_any_call("✅")
        msg.reply.assert_called_once()
        reply_text = msg.reply.call_args[0][0]
        assert "engineering team" in reply_text

    @pytest.mark.asyncio
    async def test_detail_threshold_requires_two_keywords(self):
        """A single keyword is not enough for escalation."""
        msg = _make_message(
            "There was an error when I tried to do something with the platform today"
        )
        await _handle_bug_report(msg)
        reply_text = msg.reply.call_args[0][0]
        # Should get the template prompt, not escalation
        assert "Steps to reproduce" in reply_text


# ---------------------------------------------------------------------------
# PaperclipClient
# ---------------------------------------------------------------------------


class TestPaperclipClient:
    @patch.dict("os.environ", {}, clear=True)
    def test_configured_false_when_missing_vars(self):
        pc = PaperclipClient(api_url="", api_key="", company_id="")
        assert not pc.configured

    def test_configured_true_when_set(self):
        pc = PaperclipClient(
            api_url="http://localhost:3000",
            api_key="test-key",
            company_id="comp-1",
        )
        assert pc.configured

    @pytest.mark.asyncio
    @patch.dict("os.environ", {}, clear=True)
    async def test_create_issue_returns_none_when_not_configured(self):
        pc = PaperclipClient(api_url="", api_key="", company_id="")
        result = await pc.create_issue("title", "desc")
        assert result is None

    @pytest.mark.asyncio
    async def test_create_issue_success(self):
        pc = PaperclipClient(
            api_url="http://localhost:3000",
            api_key="test-key",
            company_id="comp-1",
            project_id="proj-1",
        )
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "issue-1",
            "identifier": "TRAA-42",
            "title": "[Discord Bug] test",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("services.discord_bot.paperclip.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await pc.create_issue("[Discord Bug] test", "description")

        assert result is not None
        assert result.identifier == "TRAA-42"
        # Verify projectId was included in payload
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["projectId"] == "proj-1"

    @pytest.mark.asyncio
    async def test_create_issue_handles_http_error(self):
        import httpx

        pc = PaperclipClient(
            api_url="http://localhost:3000",
            api_key="test-key",
            company_id="comp-1",
        )
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("error", request=MagicMock(), response=mock_response)
        )

        with patch("services.discord_bot.paperclip.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await pc.create_issue("title", "desc")

        assert result is None
