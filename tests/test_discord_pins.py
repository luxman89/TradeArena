"""Tests for the Discord bot auto-pin functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from services.discord_bot.pins import (
    DISCORD_PIN_LIMIT,
    PIN_EMOJI,
    PIN_REACTION_THRESHOLD,
    _ensure_pin_capacity,
    _is_moderator,
    _pin_message,
    handle_announcement_pin,
    handle_reaction_pin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    *,
    channel_name: str = "announcements",
    pinned: bool = False,
) -> MagicMock:
    """Create a mock Discord Message for pin tests."""
    msg = MagicMock(spec=discord.Message)
    msg.id = 111222333
    msg.pinned = pinned
    msg.pin = AsyncMock()
    msg.unpin = AsyncMock()
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.name = channel_name
    msg.channel.pins = AsyncMock(return_value=[])
    msg.reactions = []
    return msg


def _make_member(*, roles: list[str] | None = None) -> MagicMock:
    """Create a mock Discord Member."""
    member = MagicMock(spec=discord.Member)
    member.display_name = "TestMod"
    if roles is None:
        roles = []
    member.roles = [MagicMock(name=r) for r in roles]
    # MagicMock overrides name, so set it explicitly
    for role_mock, role_name in zip(member.roles, roles):
        role_mock.name = role_name
    return member


def _make_reaction(emoji: str, count: int) -> MagicMock:
    """Create a mock Reaction."""
    reaction = MagicMock()
    reaction.emoji = emoji
    reaction.count = count
    return reaction


def _make_payload(
    *,
    emoji: str = "👍",
    user_id: int = 99999,
    channel_id: int = 12345,
    message_id: int = 111222333,
    guild_id: int = 54321,
    member: MagicMock | None = None,
) -> MagicMock:
    """Create a mock RawReactionActionEvent."""
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.emoji = MagicMock()
    payload.emoji.__str__ = lambda self: emoji
    payload.user_id = user_id
    payload.channel_id = channel_id
    payload.message_id = message_id
    payload.guild_id = guild_id
    payload.member = member
    return payload


# ---------------------------------------------------------------------------
# _is_moderator
# ---------------------------------------------------------------------------


class TestIsModerator:
    def test_moderator_role(self):
        member = _make_member(roles=["Moderator"])
        assert _is_moderator(member) is True

    def test_admin_role(self):
        member = _make_member(roles=["Admin"])
        assert _is_moderator(member) is True

    def test_no_mod_role(self):
        member = _make_member(roles=["Member", "Contributor"])
        assert _is_moderator(member) is False

    def test_empty_roles(self):
        member = _make_member(roles=[])
        assert _is_moderator(member) is False


# ---------------------------------------------------------------------------
# _ensure_pin_capacity
# ---------------------------------------------------------------------------


class TestEnsurePinCapacity:
    @pytest.mark.asyncio
    async def test_under_limit_no_unpin(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "test"
        pins = [MagicMock() for _ in range(10)]
        channel.pins = AsyncMock(return_value=pins)

        await _ensure_pin_capacity(channel)
        for pin in pins:
            pin.unpin.assert_not_called()

    @pytest.mark.asyncio
    async def test_at_limit_unpins_oldest(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "test"
        pins = [MagicMock() for _ in range(DISCORD_PIN_LIMIT)]
        for i, p in enumerate(pins):
            p.id = i
            p.unpin = AsyncMock()
        channel.pins = AsyncMock(return_value=pins)

        await _ensure_pin_capacity(channel)
        # Oldest = last in list (newest-first order)
        pins[-1].unpin.assert_awaited_once()
        # Others should not be unpinned
        for p in pins[:-1]:
            p.unpin.assert_not_called()

    @pytest.mark.asyncio
    async def test_forbidden_does_not_raise(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "test"
        channel.pins = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))

        # Should not raise
        await _ensure_pin_capacity(channel)


# ---------------------------------------------------------------------------
# _pin_message
# ---------------------------------------------------------------------------


class TestPinMessage:
    @pytest.mark.asyncio
    async def test_pins_unpinned_message(self):
        msg = _make_message(pinned=False)
        result = await _pin_message(msg, "test reason")
        assert result is True
        msg.pin.assert_awaited_once_with(reason="test reason")

    @pytest.mark.asyncio
    async def test_skips_already_pinned(self):
        msg = _make_message(pinned=True)
        result = await _pin_message(msg, "test reason")
        assert result is False
        msg.pin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_forbidden_returns_false(self):
        msg = _make_message(pinned=False)
        msg.pin = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
        result = await _pin_message(msg, "test reason")
        assert result is False

    @pytest.mark.asyncio
    async def test_ensures_capacity_before_pin(self):
        msg = _make_message(pinned=False)
        # Put channel at limit
        pins = [MagicMock() for _ in range(DISCORD_PIN_LIMIT)]
        for p in pins:
            p.unpin = AsyncMock()
        msg.channel.pins = AsyncMock(return_value=pins)

        await _pin_message(msg, "capacity test")
        # Oldest should have been unpinned
        pins[-1].unpin.assert_awaited_once()
        msg.pin.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle_announcement_pin
# ---------------------------------------------------------------------------


class TestHandleAnnouncementPin:
    @pytest.mark.asyncio
    async def test_pins_announcement(self):
        msg = _make_message(channel_name="announcements")
        await handle_announcement_pin(msg)
        msg.pin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ignores_non_announcement_channel(self):
        msg = _make_message(channel_name="general")
        await handle_announcement_pin(msg)
        msg.pin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_already_pinned(self):
        msg = _make_message(channel_name="announcements", pinned=True)
        await handle_announcement_pin(msg)
        msg.pin.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_reaction_pin — moderator pin emoji
# ---------------------------------------------------------------------------


class TestReactionPinModerator:
    @pytest.mark.asyncio
    async def test_moderator_pin_emoji(self):
        member = _make_member(roles=["Moderator"])
        payload = _make_payload(emoji=PIN_EMOJI, member=member)

        msg = _make_message(channel_name="general", pinned=False)
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "general"
        channel.fetch_message = AsyncMock(return_value=msg)

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        await handle_reaction_pin(payload, guild)
        msg.pin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_moderator_pin_emoji_no_pin(self):
        member = _make_member(roles=["Member"])
        payload = _make_payload(emoji=PIN_EMOJI, member=member)

        msg = _make_message(channel_name="general", pinned=False)
        msg.reactions = [_make_reaction(PIN_EMOJI, 1)]
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "general"
        channel.fetch_message = AsyncMock(return_value=msg)

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        await handle_reaction_pin(payload, guild)
        # 1 reaction < threshold, non-mod pin emoji — should not pin
        msg.pin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_already_pinned(self):
        member = _make_member(roles=["Moderator"])
        payload = _make_payload(emoji=PIN_EMOJI, member=member)

        msg = _make_message(channel_name="general", pinned=True)
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "general"
        channel.fetch_message = AsyncMock(return_value=msg)

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        await handle_reaction_pin(payload, guild)
        msg.pin.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_reaction_pin — reaction threshold
# ---------------------------------------------------------------------------


class TestReactionPinThreshold:
    @pytest.mark.asyncio
    async def test_pins_at_threshold(self):
        payload = _make_payload(emoji="🔥")

        msg = _make_message(channel_name="general", pinned=False)
        msg.reactions = [
            _make_reaction("🔥", PIN_REACTION_THRESHOLD - 1),
            _make_reaction("👍", 1),
        ]
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "general"
        channel.fetch_message = AsyncMock(return_value=msg)

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        await handle_reaction_pin(payload, guild)
        msg.pin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_pin_below_threshold(self):
        payload = _make_payload(emoji="👍")

        msg = _make_message(channel_name="general", pinned=False)
        msg.reactions = [_make_reaction("👍", 1)]
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "general"
        channel.fetch_message = AsyncMock(return_value=msg)

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        await handle_reaction_pin(payload, guild)
        msg.pin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_above_threshold_pins(self):
        payload = _make_payload(emoji="❤️")

        msg = _make_message(channel_name="general", pinned=False)
        msg.reactions = [_make_reaction("❤️", PIN_REACTION_THRESHOLD + 5)]
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "general"
        channel.fetch_message = AsyncMock(return_value=msg)

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        await handle_reaction_pin(payload, guild)
        msg.pin.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle_reaction_pin — edge cases
# ---------------------------------------------------------------------------


class TestReactionPinEdgeCases:
    @pytest.mark.asyncio
    async def test_no_channel_found(self):
        payload = _make_payload()
        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=None)

        # Should not raise
        await handle_reaction_pin(payload, guild)

    @pytest.mark.asyncio
    async def test_message_fetch_fails(self):
        payload = _make_payload()
        channel = MagicMock(spec=discord.TextChannel)
        channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "not found"))

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        # Should not raise
        await handle_reaction_pin(payload, guild)

    @pytest.mark.asyncio
    async def test_non_text_channel_ignored(self):
        payload = _make_payload()
        channel = MagicMock(spec=discord.VoiceChannel)

        guild = MagicMock(spec=discord.Guild)
        guild.get_channel = MagicMock(return_value=channel)

        # Should not raise or pin anything
        await handle_reaction_pin(payload, guild)
