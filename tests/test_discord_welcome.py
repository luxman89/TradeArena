"""Tests for Discord welcome message and rules posting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from services.discord_bot.welcome import (
    _load_welcome_and_rules,
    _split_message,
    post_welcome_and_rules,
)

# ---------------------------------------------------------------------------
# _split_message
# ---------------------------------------------------------------------------


class TestSplitMessage:
    def test_short_message_single_chunk(self):
        assert _split_message("hello", max_len=2000) == ["hello"]

    def test_splits_at_newlines(self):
        text = "line1\nline2\nline3"
        chunks = _split_message(text, max_len=10)
        assert len(chunks) >= 2
        assert all(len(c) <= 10 for c in chunks)

    def test_splits_long_line_at_max(self):
        text = "A" * 100
        chunks = _split_message(text, max_len=30)
        assert len(chunks) >= 3
        assert all(len(c) <= 30 for c in chunks)

    def test_exact_limit(self):
        text = "A" * 2000
        assert _split_message(text, max_len=2000) == [text]


# ---------------------------------------------------------------------------
# _load_welcome_and_rules
# ---------------------------------------------------------------------------


class TestLoadWelcomeAndRules:
    def test_loads_content(self):
        welcome, rules = _load_welcome_and_rules()
        # The file exists in the repo
        assert "TradeArena" in welcome or "TradeArena" in rules
        assert len(rules) > 0

    def test_rules_contain_sections(self):
        _, rules = _load_welcome_and_rules()
        assert "Respectful" in rules or "Respect" in rules


# ---------------------------------------------------------------------------
# post_welcome_and_rules
# ---------------------------------------------------------------------------


def _make_guild(*, has_rules_channel: bool = True) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.name = "TradeArena"
    guild.text_channels = []
    if has_rules_channel:
        ch = MagicMock(spec=discord.TextChannel)
        ch.name = "rules"
        ch.send = AsyncMock(return_value=MagicMock(pin=AsyncMock()))
        ch.pins = AsyncMock(return_value=[])
        guild.text_channels.append(ch)
    return guild


class TestPostWelcomeAndRules:
    @pytest.mark.asyncio
    async def test_posts_welcome_and_rules(self):
        guild = _make_guild()
        rules_ch = guild.text_channels[0]
        # Mock send to return message objects with pin()
        msg_mock = MagicMock()
        msg_mock.pin = AsyncMock()
        rules_ch.send = AsyncMock(return_value=msg_mock)

        with patch("discord.utils.get", return_value=rules_ch):
            await post_welcome_and_rules(guild)

        assert rules_ch.send.call_count >= 2  # welcome + rules

    @pytest.mark.asyncio
    async def test_skips_when_already_pinned(self):
        guild = _make_guild()
        rules_ch = guild.text_channels[0]

        # Simulate existing pinned message with marker
        existing_pin = MagicMock()
        existing_pin.author = MagicMock()
        existing_pin.author.bot = True
        existing_pin.content = "**Welcome to TradeArena!** Some content"
        rules_ch.pins = AsyncMock(return_value=[existing_pin])

        with patch("discord.utils.get", return_value=rules_ch):
            await post_welcome_and_rules(guild)

        rules_ch.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_rules_channel(self):
        guild = _make_guild(has_rules_channel=False)

        with patch("discord.utils.get", return_value=None):
            # Should not raise
            await post_welcome_and_rules(guild)

    @pytest.mark.asyncio
    async def test_handles_forbidden(self):
        guild = _make_guild()
        rules_ch = guild.text_channels[0]
        rules_ch.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))

        with patch("discord.utils.get", return_value=rules_ch):
            # Should not raise
            await post_welcome_and_rules(guild)
