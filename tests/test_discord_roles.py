"""Tests for Discord role management — rank-based and contributor role sync."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from services.discord_bot.roles import (
    CONTRIBUTOR_ROLE,
    ELITE_TRADER_ROLE,
    PRO_TRADER_ROLE,
    classify_rank,
    fetch_leaderboard_with_discord,
    fetch_recently_merged_prs,
    sync_contributor_roles,
    sync_rank_roles,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_role(name: str) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.name = name
    return role


def _make_member(
    display_name: str,
    member_id: int,
    roles: list | None = None,
    name: str | None = None,
    global_name: str | None = None,
) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.display_name = display_name
    member.id = member_id
    member.name = name or display_name.lower()
    member.global_name = global_name
    member.roles = roles or []
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


def _make_guild(
    members: list | None = None,
    roles: list | None = None,
) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.name = "TradeArena"
    guild.members = members or []
    guild.roles = roles or []
    return guild


SAMPLE_LEADERBOARD = [
    {
        "creator_id": f"creator-{i}",
        "display_name": f"Trader{i}",
        "discord_id": str(1000 + i),
        "composite_score": 1.0 - i * 0.02,
    }
    for i in range(30)
]


# ---------------------------------------------------------------------------
# classify_rank
# ---------------------------------------------------------------------------


class TestClassifyRank:
    def test_elite_range(self):
        for pos in [1, 5, 10]:
            assert classify_rank(pos) == ELITE_TRADER_ROLE

    def test_pro_range(self):
        for pos in [11, 15, 25]:
            assert classify_rank(pos) == PRO_TRADER_ROLE

    def test_no_rank(self):
        assert classify_rank(26) is None
        assert classify_rank(100) is None


# ---------------------------------------------------------------------------
# fetch_leaderboard_with_discord
# ---------------------------------------------------------------------------


class TestFetchLeaderboardWithDiscord:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"entries": SAMPLE_LEADERBOARD[:5]}
        mock_response.raise_for_status = MagicMock()

        with patch("services.discord_bot.roles.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            entries = await fetch_leaderboard_with_discord(limit=5)

        assert entries is not None
        assert len(entries) == 5

    @pytest.mark.asyncio
    async def test_error_returns_none(self):
        import httpx as httpx_mod

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx_mod.HTTPStatusError(
                "err", request=MagicMock(), response=mock_response
            )
        )

        with patch("services.discord_bot.roles.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            entries = await fetch_leaderboard_with_discord()

        assert entries is None


# ---------------------------------------------------------------------------
# sync_rank_roles
# ---------------------------------------------------------------------------


class TestSyncRankRoles:
    @pytest.mark.asyncio
    async def test_assigns_elite_role(self):
        """Top-10 leaderboard member gets Elite Trader role."""
        elite_role = _make_role(ELITE_TRADER_ROLE)
        pro_role = _make_role(PRO_TRADER_ROLE)
        # Member at position 1 (discord_id=1000)
        member = _make_member("Trader0", 1000, roles=[])
        guild = _make_guild(members=[member], roles=[elite_role, pro_role])

        entries = SAMPLE_LEADERBOARD[:25]

        with (
            patch(
                "services.discord_bot.roles.fetch_leaderboard_with_discord",
                new=AsyncMock(return_value=entries),
            ),
            patch(
                "discord.utils.get",
                side_effect=lambda roles, name: {
                    ELITE_TRADER_ROLE: elite_role,
                    PRO_TRADER_ROLE: pro_role,
                }.get(name),
            ),
        ):
            changes = await sync_rank_roles(guild)

        member.add_roles.assert_any_call(elite_role, reason="Leaderboard rank sync")
        assert len(changes["added"]) >= 1

    @pytest.mark.asyncio
    async def test_removes_elite_when_dropped(self):
        """Member who drops off leaderboard loses their rank role."""
        elite_role = _make_role(ELITE_TRADER_ROLE)
        pro_role = _make_role(PRO_TRADER_ROLE)
        # Member has Elite role but is NOT on the leaderboard
        member = _make_member("OldTrader", 9999, roles=[elite_role])
        guild = _make_guild(members=[member], roles=[elite_role, pro_role])

        entries = SAMPLE_LEADERBOARD[:25]  # Member 9999 not in entries

        with (
            patch(
                "services.discord_bot.roles.fetch_leaderboard_with_discord",
                new=AsyncMock(return_value=entries),
            ),
            patch(
                "discord.utils.get",
                side_effect=lambda roles, name: {
                    ELITE_TRADER_ROLE: elite_role,
                    PRO_TRADER_ROLE: pro_role,
                }.get(name),
            ),
        ):
            changes = await sync_rank_roles(guild)

        member.remove_roles.assert_any_call(elite_role, reason="Leaderboard rank sync")
        assert len(changes["removed"]) >= 1

    @pytest.mark.asyncio
    async def test_promotes_from_pro_to_elite(self):
        """Member moves from Pro to Elite when ranking improves."""
        elite_role = _make_role(ELITE_TRADER_ROLE)
        pro_role = _make_role(PRO_TRADER_ROLE)
        # Member at position 5 currently has Pro role
        member = _make_member("Trader4", 1004, roles=[pro_role])
        guild = _make_guild(members=[member], roles=[elite_role, pro_role])

        entries = SAMPLE_LEADERBOARD[:25]

        with (
            patch(
                "services.discord_bot.roles.fetch_leaderboard_with_discord",
                new=AsyncMock(return_value=entries),
            ),
            patch(
                "discord.utils.get",
                side_effect=lambda roles, name: {
                    ELITE_TRADER_ROLE: elite_role,
                    PRO_TRADER_ROLE: pro_role,
                }.get(name),
            ),
        ):
            await sync_rank_roles(guild)

        # Should add Elite and remove Pro
        member.add_roles.assert_any_call(elite_role, reason="Leaderboard rank sync")
        member.remove_roles.assert_any_call(pro_role, reason="Leaderboard rank sync")

    @pytest.mark.asyncio
    async def test_skips_when_no_roles_found(self):
        """Does nothing if role objects don't exist in guild."""
        guild = _make_guild(roles=[])

        with patch("discord.utils.get", return_value=None):
            changes = await sync_rank_roles(guild)

        assert changes == {"added": [], "removed": []}

    @pytest.mark.asyncio
    async def test_skips_entries_without_discord_id(self):
        """Entries without discord_id are ignored."""
        elite_role = _make_role(ELITE_TRADER_ROLE)
        pro_role = _make_role(PRO_TRADER_ROLE)
        guild = _make_guild(members=[], roles=[elite_role, pro_role])

        entries = [
            {
                "creator_id": "c1",
                "display_name": "NoDiscord",
                "discord_id": None,
                "composite_score": 0.95,
            }
        ]

        with (
            patch(
                "services.discord_bot.roles.fetch_leaderboard_with_discord",
                new=AsyncMock(return_value=entries),
            ),
            patch(
                "discord.utils.get",
                side_effect=lambda roles, name: {
                    ELITE_TRADER_ROLE: elite_role,
                    PRO_TRADER_ROLE: pro_role,
                }.get(name),
            ),
        ):
            changes = await sync_rank_roles(guild)

        assert changes == {"added": [], "removed": []}

    @pytest.mark.asyncio
    async def test_handles_leaderboard_fetch_failure(self):
        """Returns empty changes when leaderboard fetch fails."""
        elite_role = _make_role(ELITE_TRADER_ROLE)
        guild = _make_guild(roles=[elite_role])

        with (
            patch(
                "services.discord_bot.roles.fetch_leaderboard_with_discord",
                new=AsyncMock(return_value=None),
            ),
            patch("discord.utils.get", return_value=elite_role),
        ):
            changes = await sync_rank_roles(guild)

        assert changes == {"added": [], "removed": []}


# ---------------------------------------------------------------------------
# fetch_recently_merged_prs
# ---------------------------------------------------------------------------


SAMPLE_PRS = [
    {
        "number": 42,
        "merged_at": "2026-03-20T10:00:00Z",
        "user": {"login": "alice"},
        "title": "Add feature X",
    },
    {
        "number": 43,
        "merged_at": "2026-03-21T10:00:00Z",
        "user": {"login": "bob"},
        "title": "Fix bug Y",
    },
    {
        "number": 44,
        "merged_at": None,  # not merged
        "user": {"login": "carol"},
        "title": "WIP",
    },
]


class TestFetchRecentlyMergedPrs:
    @pytest.mark.asyncio
    async def test_returns_only_merged(self):
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_PRS
        mock_response.raise_for_status = MagicMock()

        with patch("services.discord_bot.roles.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            prs = await fetch_recently_merged_prs()

        assert len(prs) == 2
        assert prs[0]["user_login"] == "alice"
        assert prs[1]["user_login"] == "bob"

    @pytest.mark.asyncio
    async def test_error_returns_empty(self):
        import httpx as httpx_mod

        with patch("services.discord_bot.roles.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx_mod.ConnectError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            prs = await fetch_recently_merged_prs()

        assert prs == []


# ---------------------------------------------------------------------------
# sync_contributor_roles
# ---------------------------------------------------------------------------


class TestSyncContributorRoles:
    @pytest.mark.asyncio
    async def test_assigns_contributor_role(self):
        """Member matching a merged PR author gets Contributor role."""
        import services.discord_bot.roles as roles_mod

        contributor_role = _make_role(CONTRIBUTOR_ROLE)
        # Member "alice" matches PR author "alice"
        member = _make_member("Alice", 2000, roles=[], name="alice")
        guild = _make_guild(members=[member], roles=[contributor_role])

        merged_prs = [{"number": 100, "user_login": "alice", "title": "Add feature"}]

        # Clear processed PRs for test isolation
        original = roles_mod._processed_prs.copy()
        roles_mod._processed_prs.clear()

        try:
            with (
                patch(
                    "services.discord_bot.roles.fetch_recently_merged_prs",
                    new=AsyncMock(return_value=merged_prs),
                ),
                patch("discord.utils.get", return_value=contributor_role),
            ):
                changes = await sync_contributor_roles(guild)
        finally:
            roles_mod._processed_prs = original

        member.add_roles.assert_called_once_with(contributor_role, reason="Merged PR on GitHub")
        assert "Alice" in changes["added"]

    @pytest.mark.asyncio
    async def test_skips_already_assigned(self):
        """Members who already have Contributor role are not re-assigned."""
        import services.discord_bot.roles as roles_mod

        contributor_role = _make_role(CONTRIBUTOR_ROLE)
        member = _make_member("Alice", 2000, roles=[contributor_role], name="alice")
        guild = _make_guild(members=[member], roles=[contributor_role])

        merged_prs = [{"number": 200, "user_login": "alice", "title": "Another PR"}]

        original = roles_mod._processed_prs.copy()
        roles_mod._processed_prs.clear()

        try:
            with (
                patch(
                    "services.discord_bot.roles.fetch_recently_merged_prs",
                    new=AsyncMock(return_value=merged_prs),
                ),
                patch("discord.utils.get", return_value=contributor_role),
            ):
                changes = await sync_contributor_roles(guild)
        finally:
            roles_mod._processed_prs = original

        member.add_roles.assert_not_called()
        assert changes["added"] == []

    @pytest.mark.asyncio
    async def test_deduplicates_processed_prs(self):
        """Already-processed PR numbers are not re-checked."""
        import services.discord_bot.roles as roles_mod

        contributor_role = _make_role(CONTRIBUTOR_ROLE)
        member = _make_member("Alice", 2000, roles=[], name="alice")
        guild = _make_guild(members=[member], roles=[contributor_role])

        merged_prs = [{"number": 300, "user_login": "alice", "title": "PR"}]

        original = roles_mod._processed_prs.copy()
        roles_mod._processed_prs = {300}  # Already processed

        try:
            with (
                patch(
                    "services.discord_bot.roles.fetch_recently_merged_prs",
                    new=AsyncMock(return_value=merged_prs),
                ),
                patch("discord.utils.get", return_value=contributor_role),
            ):
                await sync_contributor_roles(guild)
        finally:
            roles_mod._processed_prs = original

        member.add_roles.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_contributor_role_in_guild(self):
        """Does nothing if Contributor role doesn't exist."""
        guild = _make_guild(roles=[])

        with patch("discord.utils.get", return_value=None):
            changes = await sync_contributor_roles(guild)

        assert changes == {"added": []}

    @pytest.mark.asyncio
    async def test_matches_display_name(self):
        """Matches by display_name (case-insensitive)."""
        import services.discord_bot.roles as roles_mod

        contributor_role = _make_role(CONTRIBUTOR_ROLE)
        member = _make_member("Bob Builder", 2001, roles=[], name="bob_d", global_name="bob")
        guild = _make_guild(members=[member], roles=[contributor_role])

        merged_prs = [{"number": 400, "user_login": "bob", "title": "Fix"}]

        original = roles_mod._processed_prs.copy()
        roles_mod._processed_prs.clear()

        try:
            with (
                patch(
                    "services.discord_bot.roles.fetch_recently_merged_prs",
                    new=AsyncMock(return_value=merged_prs),
                ),
                patch("discord.utils.get", return_value=contributor_role),
            ):
                changes = await sync_contributor_roles(guild)
        finally:
            roles_mod._processed_prs = original

        member.add_roles.assert_called_once()
        assert "Bob Builder" in changes["added"]
