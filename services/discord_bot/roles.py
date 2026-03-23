"""Discord role management — rank-based roles and contributor role assignment.

Assigns/removes Discord roles based on:
- Leaderboard position: Elite Trader (top N) and Pro Trader (top M)
- GitHub contributions: Contributor role for users with merged PRs
"""

from __future__ import annotations

import logging
import os

import discord
import httpx

log = logging.getLogger("tradearena.bot.roles")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Role names — must match the roles created on the Discord server
ELITE_TRADER_ROLE = "Elite Trader"
PRO_TRADER_ROLE = "Pro Trader"
CONTRIBUTOR_ROLE = "Contributor"

# Position thresholds on the global leaderboard (1-indexed)
ELITE_THRESHOLD = int(os.getenv("ELITE_TRADER_THRESHOLD", "10"))
PRO_THRESHOLD = int(os.getenv("PRO_TRADER_THRESHOLD", "25"))

# GitHub config (reuses existing env vars from bot.py)
GITHUB_REPO = os.getenv("GITHUB_REPO", "luxman89/TradeArena")

# TradeArena API
TRADEARENA_API_URL = os.getenv("TRADEARENA_API_URL", "http://localhost:8000").rstrip("/")

# ---------------------------------------------------------------------------
# Rank-based role sync
# ---------------------------------------------------------------------------

RANK_ROLES = {ELITE_TRADER_ROLE, PRO_TRADER_ROLE}


async def fetch_leaderboard_with_discord(limit: int = 50) -> list[dict] | None:
    """Fetch leaderboard entries including discord_id for role mapping."""
    url = f"{TRADEARENA_API_URL}/leaderboard?limit={limit}"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            return resp.json().get("entries", [])
    except Exception:
        log.exception("Failed to fetch leaderboard for role sync")
        return None


def classify_rank(position: int) -> str | None:
    """Return the rank role name for a 1-indexed leaderboard position, or None."""
    if position <= ELITE_THRESHOLD:
        return ELITE_TRADER_ROLE
    if position <= PRO_THRESHOLD:
        return PRO_TRADER_ROLE
    return None


async def sync_rank_roles(guild: discord.Guild) -> dict:
    """Sync Elite Trader / Pro Trader roles based on leaderboard position.

    Returns a dict summarizing changes: {"added": [...], "removed": [...]}.
    """
    changes: dict[str, list[str]] = {"added": [], "removed": []}

    elite_role = discord.utils.get(guild.roles, name=ELITE_TRADER_ROLE)
    pro_role = discord.utils.get(guild.roles, name=PRO_TRADER_ROLE)
    if not elite_role and not pro_role:
        log.warning(
            "Neither '%s' nor '%s' role found in %s — skipping rank sync",
            ELITE_TRADER_ROLE,
            PRO_TRADER_ROLE,
            guild.name,
        )
        return changes

    entries = await fetch_leaderboard_with_discord(limit=PRO_THRESHOLD)
    if entries is None:
        return changes

    # Build mapping: discord_id -> desired rank role name
    desired: dict[str, str] = {}
    for i, entry in enumerate(entries, start=1):
        discord_id = entry.get("discord_id")
        if not discord_id:
            continue
        rank = classify_rank(i)
        if rank:
            desired[discord_id] = rank

    # Collect all guild members who currently have rank roles
    role_map = {ELITE_TRADER_ROLE: elite_role, PRO_TRADER_ROLE: pro_role}

    for member in guild.members:
        member_discord_id = str(member.id)
        target_rank = desired.get(member_discord_id)

        for role_name, role_obj in role_map.items():
            if role_obj is None:
                continue
            has_role = role_obj in member.roles
            should_have = target_rank == role_name

            if should_have and not has_role:
                try:
                    await member.add_roles(role_obj, reason="Leaderboard rank sync")
                    changes["added"].append(f"{member.display_name} -> {role_name}")
                    log.info("Assigned %s to %s", role_name, member.display_name)
                except discord.Forbidden:
                    log.error("Missing permission to assign %s to %s", role_name, member)
            elif not should_have and has_role:
                try:
                    await member.remove_roles(role_obj, reason="Leaderboard rank sync")
                    changes["removed"].append(f"{member.display_name} x {role_name}")
                    log.info("Removed %s from %s", role_name, member.display_name)
                except discord.Forbidden:
                    log.error("Missing permission to remove %s from %s", role_name, member)

    return changes


# ---------------------------------------------------------------------------
# Contributor role — GitHub merged-PR polling
# ---------------------------------------------------------------------------

# Track PR numbers we already processed to avoid re-assigning
_processed_prs: set[int] = set()


async def fetch_recently_merged_prs(since_pages: int = 1) -> list[dict]:
    """Fetch recently merged PRs from GitHub.

    Returns a list of dicts with 'number', 'user_login', and 'title'.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/pulls"
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    results = []
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            for page in range(1, since_pages + 1):
                resp = await http.get(
                    url,
                    headers=headers,
                    params={
                        "state": "closed",
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": 30,
                        "page": page,
                    },
                )
                resp.raise_for_status()
                for pr in resp.json():
                    if pr.get("merged_at") and pr.get("user", {}).get("login"):
                        results.append(
                            {
                                "number": pr["number"],
                                "user_login": pr["user"]["login"],
                                "title": pr.get("title", ""),
                            }
                        )
    except Exception:
        log.exception("Failed to fetch merged PRs from GitHub")

    return results


async def sync_contributor_roles(guild: discord.Guild) -> dict:
    """Assign Contributor role to guild members who have merged PRs.

    Matches GitHub username to Discord member display_name or username
    (case-insensitive). Returns a summary of changes.
    """
    changes: dict[str, list[str]] = {"added": []}

    contributor_role = discord.utils.get(guild.roles, name=CONTRIBUTOR_ROLE)
    if not contributor_role:
        log.warning(
            "No '%s' role found in %s — skipping contributor sync", CONTRIBUTOR_ROLE, guild.name
        )
        return changes

    merged_prs = await fetch_recently_merged_prs()
    if not merged_prs:
        return changes

    # Collect unique GitHub usernames from new (unprocessed) merged PRs
    new_authors: set[str] = set()
    for pr in merged_prs:
        pr_num = pr["number"]
        if pr_num not in _processed_prs:
            _processed_prs.add(pr_num)
            new_authors.add(pr["user_login"].lower())

    if not new_authors:
        return changes

    # Build lookup of guild members by name variations (case-insensitive)
    for member in guild.members:
        if contributor_role in member.roles:
            continue  # Already has the role
        names = {member.name.lower(), member.display_name.lower()}
        if member.global_name:
            names.add(member.global_name.lower())

        if names & new_authors:
            try:
                await member.add_roles(contributor_role, reason="Merged PR on GitHub")
                changes["added"].append(member.display_name)
                log.info(
                    "Assigned %s to %s (GitHub contributor)", CONTRIBUTOR_ROLE, member.display_name
                )
            except discord.Forbidden:
                log.error("Missing permission to assign %s to %s", CONTRIBUTOR_ROLE, member)

    return changes
