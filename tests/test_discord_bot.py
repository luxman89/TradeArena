"""Tests for the Discord bot — bug report escalation, leaderboard, and changelog posting."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.discord_bot.bot import (
    _build_issue_description,
    _extract_bug_title,
    _handle_bug_report,
    build_changelog_embed,
    build_leaderboard_embed,
    check_changelog,
    fetch_latest_release,
    fetch_leaderboard,
    post_leaderboard,
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


# ---------------------------------------------------------------------------
# Leaderboard — build_leaderboard_embed
# ---------------------------------------------------------------------------

SAMPLE_ENTRIES = [
    {
        "creator_id": "alice-a1b2",
        "display_name": "Alice",
        "composite_score": 0.85,
        "win_rate": 0.72,
        "total_signals": 50,
    },
    {
        "creator_id": "bob-c3d4",
        "display_name": "Bob",
        "composite_score": 0.78,
        "win_rate": 0.65,
        "total_signals": 30,
    },
    {
        "creator_id": "carol-e5f6",
        "display_name": "Carol",
        "composite_score": 0.71,
        "win_rate": 0.60,
        "total_signals": 25,
    },
]


class TestBuildLeaderboardEmbed:
    def test_embed_title(self):
        embed = build_leaderboard_embed(SAMPLE_ENTRIES)
        assert "Leaderboard" in embed.title

    def test_embed_contains_trader_names(self):
        embed = build_leaderboard_embed(SAMPLE_ENTRIES)
        field_value = embed.fields[0].value
        assert "Alice" in field_value
        assert "Bob" in field_value
        assert "Carol" in field_value

    def test_embed_contains_scores(self):
        embed = build_leaderboard_embed(SAMPLE_ENTRIES)
        field_value = embed.fields[0].value
        assert "0.85" in field_value
        assert "0.78" in field_value

    def test_embed_medals_for_top_three(self):
        embed = build_leaderboard_embed(SAMPLE_ENTRIES)
        field_value = embed.fields[0].value
        assert "🥇" in field_value
        assert "🥈" in field_value
        assert "🥉" in field_value

    def test_empty_entries(self):
        embed = build_leaderboard_embed([])
        assert any("No" in f.value for f in embed.fields)

    def test_embed_color_set(self):
        embed = build_leaderboard_embed(SAMPLE_ENTRIES)
        assert embed.color is not None


# ---------------------------------------------------------------------------
# Leaderboard — fetch_leaderboard
# ---------------------------------------------------------------------------


class TestFetchLeaderboard:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"entries": SAMPLE_ENTRIES, "total": 3}
        mock_response.raise_for_status = MagicMock()

        with patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            entries = await fetch_leaderboard(limit=10)

        assert entries is not None
        assert len(entries) == 3
        assert entries[0]["display_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        import httpx as httpx_mod

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx_mod.HTTPStatusError(
                "error", request=MagicMock(), response=mock_response
            )
        )

        with patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            entries = await fetch_leaderboard()

        assert entries is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self):
        import httpx as httpx_mod

        with patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            entries = await fetch_leaderboard()

        assert entries is None


# ---------------------------------------------------------------------------
# Leaderboard — post_leaderboard duplicate guard
# ---------------------------------------------------------------------------


class TestPostLeaderboardDedup:
    @pytest.mark.asyncio
    async def test_skips_when_recently_posted(self):
        """Should skip if last post was less than an hour ago."""
        import services.discord_bot.bot as bot_mod

        original = bot_mod._last_leaderboard_post
        try:
            bot_mod._last_leaderboard_post = datetime.now(UTC)
            with patch.object(bot_mod, "fetch_leaderboard") as mock_fetch:
                await post_leaderboard()
                mock_fetch.assert_not_called()
        finally:
            bot_mod._last_leaderboard_post = original


# ---------------------------------------------------------------------------
# Changelog — fetch_latest_release
# ---------------------------------------------------------------------------

SAMPLE_RELEASE = {
    "tag_name": "v0.3.0",
    "name": "v0.3.0 — Changelog Posting",
    "body": "## What's Changed\n- Added changelog posting to Discord\n- Bug fixes",
    "html_url": "https://github.com/luxman89/TradeArena/releases/tag/v0.3.0",
    "published_at": "2026-03-23T10:00:00Z",
}


class TestFetchLatestRelease:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RELEASE
        mock_response.raise_for_status = MagicMock()

        with patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            release = await fetch_latest_release()

        assert release is not None
        assert release["tag_name"] == "v0.3.0"

    @pytest.mark.asyncio
    async def test_404_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            release = await fetch_latest_release()

        assert release is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        import httpx as httpx_mod

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx_mod.HTTPStatusError(
                "error", request=MagicMock(), response=mock_response
            )
        )

        with patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            release = await fetch_latest_release()

        assert release is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self):
        import httpx as httpx_mod

        with patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            release = await fetch_latest_release()

        assert release is None

    @pytest.mark.asyncio
    async def test_includes_github_token_when_set(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RELEASE
        mock_response.raise_for_status = MagicMock()

        with (
            patch("services.discord_bot.bot.httpx.AsyncClient") as mock_cls,
            patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test123"}),
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await fetch_latest_release()

            call_kwargs = mock_client.get.call_args
            headers = call_kwargs[1].get("headers", call_kwargs.kwargs.get("headers", {}))
            assert "Bearer ghp_test123" in headers.get("Authorization", "")


# ---------------------------------------------------------------------------
# Changelog — build_changelog_embed
# ---------------------------------------------------------------------------


class TestBuildChangelogEmbed:
    def test_embed_title_contains_release_name(self):
        embed = build_changelog_embed(SAMPLE_RELEASE)
        assert "v0.3.0" in embed.title

    def test_embed_description_contains_body(self):
        embed = build_changelog_embed(SAMPLE_RELEASE)
        assert "changelog posting" in embed.description.lower()

    def test_embed_has_version_field(self):
        embed = build_changelog_embed(SAMPLE_RELEASE)
        version_field = next((f for f in embed.fields if f.name == "Version"), None)
        assert version_field is not None
        assert "v0.3.0" in version_field.value

    def test_embed_has_changelog_link(self):
        embed = build_changelog_embed(SAMPLE_RELEASE)
        link_field = next((f for f in embed.fields if f.name == "Full Changelog"), None)
        assert link_field is not None
        assert "github.com" in link_field.value

    def test_embed_color_is_green(self):
        embed = build_changelog_embed(SAMPLE_RELEASE)
        assert embed.color is not None
        assert embed.color.value == 0x2ECC71

    def test_embed_url_set(self):
        embed = build_changelog_embed(SAMPLE_RELEASE)
        assert embed.url == SAMPLE_RELEASE["html_url"]

    def test_embed_timestamp_from_published_at(self):
        embed = build_changelog_embed(SAMPLE_RELEASE)
        assert embed.timestamp is not None

    def test_truncates_long_body(self):
        long_release = {**SAMPLE_RELEASE, "body": "A" * 3000}
        embed = build_changelog_embed(long_release)
        assert len(embed.description) <= 2000

    def test_handles_empty_body(self):
        no_body = {**SAMPLE_RELEASE, "body": ""}
        embed = build_changelog_embed(no_body)
        assert "No release notes" in embed.description

    def test_handles_none_body(self):
        no_body = {**SAMPLE_RELEASE, "body": None}
        embed = build_changelog_embed(no_body)
        assert "No release notes" in embed.description

    def test_fallback_name_to_tag(self):
        no_name = {**SAMPLE_RELEASE, "name": None}
        embed = build_changelog_embed(no_name)
        assert "v0.3.0" in embed.title


# ---------------------------------------------------------------------------
# Changelog — check_changelog dedup and posting
# ---------------------------------------------------------------------------


class TestCheckChangelog:
    @pytest.mark.asyncio
    async def test_initializes_tag_on_first_run(self):
        """First run should record the tag without posting."""
        import services.discord_bot.bot as bot_mod

        original = bot_mod._last_changelog_tag
        try:
            bot_mod._last_changelog_tag = None
            with patch.object(
                bot_mod, "fetch_latest_release", new=AsyncMock(return_value=SAMPLE_RELEASE)
            ):
                with patch.object(bot_mod, "client") as mock_client:
                    mock_client.guilds = []
                    await check_changelog()

            assert bot_mod._last_changelog_tag == "v0.3.0"
            # No guilds iterated = no posting happened
        finally:
            bot_mod._last_changelog_tag = original

    @pytest.mark.asyncio
    async def test_skips_same_tag(self):
        """Should not post if the tag hasn't changed."""
        import services.discord_bot.bot as bot_mod

        original = bot_mod._last_changelog_tag
        try:
            bot_mod._last_changelog_tag = "v0.3.0"
            with patch.object(
                bot_mod, "fetch_latest_release", new=AsyncMock(return_value=SAMPLE_RELEASE)
            ):
                with patch.object(bot_mod, "client") as mock_client:
                    mock_client.guilds = []
                    await check_changelog()

            # Tag unchanged, no posting
            assert bot_mod._last_changelog_tag == "v0.3.0"
        finally:
            bot_mod._last_changelog_tag = original

    @pytest.mark.asyncio
    async def test_posts_on_new_tag(self):
        """Should post when a new tag is detected."""
        import services.discord_bot.bot as bot_mod

        original = bot_mod._last_changelog_tag
        try:
            bot_mod._last_changelog_tag = "v0.2.0"  # Old tag

            mock_channel = MagicMock()
            mock_channel.name = "announcements"
            mock_channel.send = AsyncMock()

            mock_guild = MagicMock()
            mock_guild.name = "TradeArena"
            mock_guild.text_channels = [mock_channel]

            with patch.object(
                bot_mod, "fetch_latest_release", new=AsyncMock(return_value=SAMPLE_RELEASE)
            ):
                with patch.object(bot_mod, "client") as mock_client:
                    mock_client.guilds = [mock_guild]
                    with patch("discord.utils.get", return_value=mock_channel):
                        await check_changelog()

            assert bot_mod._last_changelog_tag == "v0.3.0"
            mock_channel.send.assert_called_once()
            # Verify it sent an embed
            call_kwargs = mock_channel.send.call_args
            assert "embed" in call_kwargs.kwargs
        finally:
            bot_mod._last_changelog_tag = original

    @pytest.mark.asyncio
    async def test_no_release_does_nothing(self):
        """Should do nothing if no release is found."""
        import services.discord_bot.bot as bot_mod

        original = bot_mod._last_changelog_tag
        try:
            bot_mod._last_changelog_tag = "v0.2.0"
            with patch.object(bot_mod, "fetch_latest_release", new=AsyncMock(return_value=None)):
                await check_changelog()

            assert bot_mod._last_changelog_tag == "v0.2.0"  # Unchanged
        finally:
            bot_mod._last_changelog_tag = original
