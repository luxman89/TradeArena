"""Tests for Discord server auto-setup (channels, categories, roles)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from services.discord_bot.setup import (
    ROLE_SPECS,
    SERVER_STRUCTURE,
    ensure_channels,
    ensure_roles,
    setup_server,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_guild(
    *,
    categories: list[str] | None = None,
    channels: list[str] | None = None,
    roles: list[str] | None = None,
) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.name = "TradeArena"

    # Categories
    cat_mocks = []
    for name in categories or []:
        cat = MagicMock(spec=discord.CategoryChannel)
        cat.name = name
        cat_mocks.append(cat)
    guild.categories = cat_mocks

    # Channels
    ch_mocks = []
    for name in channels or []:
        ch = MagicMock(spec=discord.TextChannel)
        ch.name = name
        ch_mocks.append(ch)
    guild.text_channels = ch_mocks

    # Roles
    role_mocks = []
    for name in roles or []:
        r = MagicMock(spec=discord.Role)
        r.name = name
        role_mocks.append(r)
    guild.roles = role_mocks

    guild.default_role = MagicMock(spec=discord.Role)
    guild.default_role.name = "@everyone"

    guild.create_category = AsyncMock()
    guild.create_text_channel = AsyncMock()
    guild.create_role = AsyncMock()

    return guild


# ---------------------------------------------------------------------------
# ensure_roles
# ---------------------------------------------------------------------------


class TestEnsureRoles:
    @pytest.mark.asyncio
    async def test_creates_missing_roles(self):
        guild = _make_guild(roles=[])
        await ensure_roles(guild)
        assert guild.create_role.call_count == len(ROLE_SPECS)

    @pytest.mark.asyncio
    async def test_skips_existing_roles(self):
        existing = [str(spec["name"]) for spec in ROLE_SPECS]
        guild = _make_guild(roles=existing)
        await ensure_roles(guild)
        guild.create_role.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_only_missing(self):
        guild = _make_guild(roles=["Admin", "Moderator"])
        await ensure_roles(guild)
        expected_creates = len(ROLE_SPECS) - 2
        assert guild.create_role.call_count == expected_creates

    @pytest.mark.asyncio
    async def test_handles_forbidden(self):
        guild = _make_guild(roles=[])
        guild.create_role = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
        # Should not raise
        result = await ensure_roles(guild)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# ensure_channels
# ---------------------------------------------------------------------------


class TestEnsureChannels:
    @pytest.mark.asyncio
    async def test_creates_all_categories_and_channels(self):
        guild = _make_guild()
        # Return mock category from create_category
        mock_cat = MagicMock(spec=discord.CategoryChannel)
        guild.create_category = AsyncMock(return_value=mock_cat)
        mock_ch = MagicMock(spec=discord.TextChannel)
        mock_ch.name = "test"
        guild.create_text_channel = AsyncMock(return_value=mock_ch)

        await ensure_channels(guild)

        assert guild.create_category.call_count == len(SERVER_STRUCTURE)
        total_channels = sum(len(cat.channels) for cat in SERVER_STRUCTURE)
        assert guild.create_text_channel.call_count == total_channels

    @pytest.mark.asyncio
    async def test_skips_existing_categories(self):
        existing_cats = [cat.name for cat in SERVER_STRUCTURE]
        guild = _make_guild(categories=existing_cats)
        mock_ch = MagicMock(spec=discord.TextChannel)
        mock_ch.name = "test"
        guild.create_text_channel = AsyncMock(return_value=mock_ch)

        await ensure_channels(guild)
        guild.create_category.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_existing_channels(self):
        all_channels = []
        for cat in SERVER_STRUCTURE:
            for ch in cat.channels:
                all_channels.append(ch.name)
        guild = _make_guild(channels=all_channels)

        mock_cat = MagicMock(spec=discord.CategoryChannel)
        guild.create_category = AsyncMock(return_value=mock_cat)

        await ensure_channels(guild)
        guild.create_text_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_only_channels_have_overwrites(self):
        guild = _make_guild()
        mock_cat = MagicMock(spec=discord.CategoryChannel)
        guild.create_category = AsyncMock(return_value=mock_cat)
        mock_ch = MagicMock(spec=discord.TextChannel)
        mock_ch.name = "test"
        guild.create_text_channel = AsyncMock(return_value=mock_ch)

        await ensure_channels(guild)

        # Check that read-only channels got permission overwrites
        for call in guild.create_text_channel.call_args_list:
            kwargs = call.kwargs
            channel_name = call.args[0] if call.args else kwargs.get("name", "")
            # Find spec for this channel
            is_read_only = False
            for cat in SERVER_STRUCTURE:
                for ch_spec in cat.channels:
                    if ch_spec.name == channel_name and ch_spec.read_only:
                        is_read_only = True
            if is_read_only:
                assert kwargs.get("overwrites"), (
                    f"Read-only channel #{channel_name} should have overwrites"
                )

    @pytest.mark.asyncio
    async def test_handles_category_create_forbidden(self):
        guild = _make_guild()
        guild.create_category = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
        # Should not raise — channels for that category are skipped
        await ensure_channels(guild)


# ---------------------------------------------------------------------------
# setup_server
# ---------------------------------------------------------------------------


class TestSetupServer:
    @pytest.mark.asyncio
    async def test_calls_both_ensure_functions(self):
        guild = _make_guild()
        with (
            patch(
                "services.discord_bot.setup.ensure_roles",
                new=AsyncMock(return_value={}),
            ) as mock_roles,
            patch(
                "services.discord_bot.setup.ensure_channels",
                new=AsyncMock(return_value={}),
            ) as mock_channels,
        ):
            await setup_server(guild)
            mock_roles.assert_awaited_once_with(guild)
            mock_channels.assert_awaited_once_with(guild)
