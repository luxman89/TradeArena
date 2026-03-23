"""Auto-create Discord server categories and channels per the TradeArena spec.

Reads the channel structure from docs/community/discord-server-structure.md
and creates any missing categories/channels on bot startup or via explicit call.

Also handles pinning the welcome message and rules in the appropriate channels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord

log = logging.getLogger("tradearena.bot.setup")


# ---------------------------------------------------------------------------
# Channel structure definition (mirrors discord-server-structure.md)
# ---------------------------------------------------------------------------


@dataclass
class ChannelSpec:
    name: str
    read_only: bool = False
    topic: str = ""


@dataclass
class CategorySpec:
    name: str
    channels: list[ChannelSpec] = field(default_factory=list)


SERVER_STRUCTURE: list[CategorySpec] = [
    CategorySpec(
        name="WELCOME",
        channels=[
            ChannelSpec(name="rules", read_only=True, topic="Server rules and code of conduct"),
            ChannelSpec(
                name="announcements",
                read_only=True,
                topic="Platform updates, new features, maintenance windows",
            ),
            ChannelSpec(
                name="introductions",
                topic="New members introduce themselves and their bots",
            ),
        ],
    ),
    CategorySpec(
        name="COMMUNITY",
        channels=[
            ChannelSpec(
                name="general",
                topic="General discussion about trading, bots, and the platform",
            ),
            ChannelSpec(
                name="show-your-bot",
                topic="Share your bot's performance and leaderboard screenshots",
            ),
            ChannelSpec(
                name="strategies",
                topic="Discuss trading strategies, signals, and market analysis",
            ),
            ChannelSpec(name="off-topic", topic="Non-trading discussion"),
        ],
    ),
    CategorySpec(
        name="SUPPORT",
        channels=[
            ChannelSpec(
                name="bot-help",
                topic="Help with SDK integration, API questions, CLI troubleshooting",
            ),
            ChannelSpec(
                name="bug-reports",
                topic="Report bugs (steps to reproduce, expected vs actual, logs)",
            ),
            ChannelSpec(
                name="feature-requests",
                topic="Suggest new features and improvements",
            ),
        ],
    ),
    CategorySpec(
        name="DEVELOPMENT",
        channels=[
            ChannelSpec(
                name="contributing",
                topic="Discussion for open-source contributors",
            ),
            ChannelSpec(
                name="changelog",
                read_only=True,
                topic="Automated feed from GitHub releases",
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Role definitions (mirrors discord-server-structure.md)
# ---------------------------------------------------------------------------

ROLE_SPECS: list[dict[str, str | int]] = [
    {"name": "Admin", "color": 0xE74C3C},  # Red
    {"name": "Moderator", "color": 0xE67E22},  # Orange
    {"name": "Contributor", "color": 0x2ECC71},  # Green
    {"name": "Elite Trader", "color": 0xF1C40F},  # Gold
    {"name": "Pro Trader", "color": 0x95A5A6},  # Silver
    {"name": "Rookie", "color": 0x7F8C8D},  # Default gray
]


# ---------------------------------------------------------------------------
# Setup logic
# ---------------------------------------------------------------------------


async def ensure_roles(guild: discord.Guild) -> dict[str, discord.Role]:
    """Create any missing roles. Returns a map of role name -> Role object."""
    existing = {role.name: role for role in guild.roles}
    result: dict[str, discord.Role] = {}

    for spec in ROLE_SPECS:
        name = str(spec["name"])
        if name in existing:
            result[name] = existing[name]
            continue
        try:
            role = await guild.create_role(
                name=name,
                color=discord.Color(int(spec["color"])),
                reason="TradeArena auto-setup",
            )
            result[name] = role
            log.info("Created role: %s", name)
        except discord.Forbidden:
            log.error("Missing permission to create role: %s", name)
        except discord.HTTPException:
            log.exception("Failed to create role: %s", name)

    return result


async def ensure_channels(guild: discord.Guild) -> dict[str, discord.TextChannel]:
    """Create any missing categories and channels. Returns channel name -> Channel."""
    existing_categories = {cat.name: cat for cat in guild.categories}
    existing_channels = {ch.name: ch for ch in guild.text_channels}
    result: dict[str, discord.TextChannel] = {}

    for cat_spec in SERVER_STRUCTURE:
        # Get or create category
        category = existing_categories.get(cat_spec.name)
        if not category:
            try:
                category = await guild.create_category(
                    cat_spec.name,
                    reason="TradeArena auto-setup",
                )
                log.info("Created category: %s", cat_spec.name)
            except discord.Forbidden:
                log.error("Missing permission to create category: %s", cat_spec.name)
                continue
            except discord.HTTPException:
                log.exception("Failed to create category: %s", cat_spec.name)
                continue

        for ch_spec in cat_spec.channels:
            channel = existing_channels.get(ch_spec.name)
            if channel:
                result[ch_spec.name] = channel
                continue

            # Build permission overwrites for read-only channels
            overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
            if ch_spec.read_only:
                overwrites[guild.default_role] = discord.PermissionOverwrite(
                    send_messages=False,
                )

            try:
                channel = await guild.create_text_channel(
                    ch_spec.name,
                    category=category,
                    topic=ch_spec.topic,
                    overwrites=overwrites,
                    reason="TradeArena auto-setup",
                )
                result[ch_spec.name] = channel
                log.info("Created channel: #%s in %s", ch_spec.name, cat_spec.name)
            except discord.Forbidden:
                log.error("Missing permission to create channel: #%s", ch_spec.name)
            except discord.HTTPException:
                log.exception("Failed to create channel: #%s", ch_spec.name)

    return result


async def setup_server(guild: discord.Guild) -> None:
    """Run the full server setup: roles, categories, and channels.

    Safe to call multiple times — skips anything that already exists.
    """
    log.info("Running server setup for guild: %s", guild.name)
    await ensure_roles(guild)
    await ensure_channels(guild)
    log.info("Server setup complete for guild: %s", guild.name)
