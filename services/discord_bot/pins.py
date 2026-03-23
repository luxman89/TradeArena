"""Auto-pin logic for the TradeArena Discord bot.

Handles:
- Pinning announcement posts in #announcements
- Pinning messages with high reaction counts (configurable threshold)
- Pinning messages when a moderator reacts with a 📌 emoji
- Unpinning oldest pins when a channel hits the 50-pin limit
"""

from __future__ import annotations

import logging
import os

import discord

log = logging.getLogger("tradearena.bot.pins")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Reaction count threshold for auto-pinning (configurable via env)
PIN_REACTION_THRESHOLD = int(os.getenv("PIN_REACTION_THRESHOLD", "5"))

# Emoji that triggers moderator-initiated pinning
PIN_EMOJI = "📌"

# Discord hard limit on pins per channel
DISCORD_PIN_LIMIT = 50

# Channels where announcement auto-pin applies
ANNOUNCEMENTS_CHANNEL = "announcements"

# Role names that count as "moderator" for pin-emoji pinning
MODERATOR_ROLES = {"Admin", "Moderator"}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


async def _ensure_pin_capacity(channel: discord.TextChannel) -> None:
    """Unpin the oldest pin if the channel is at the 50-pin limit."""
    try:
        pins = await channel.pins()
    except discord.Forbidden:
        log.warning("Missing permission to read pins in #%s", channel.name)
        return

    if len(pins) < DISCORD_PIN_LIMIT:
        return

    # Pins are returned newest-first; unpin the last (oldest) one
    oldest = pins[-1]
    try:
        await oldest.unpin()
        log.info(
            "Unpinned oldest message (id=%s) in #%s to make room",
            oldest.id,
            channel.name,
        )
    except discord.Forbidden:
        log.warning("Missing permission to unpin in #%s", channel.name)
    except discord.HTTPException:
        log.exception("Failed to unpin oldest message in #%s", channel.name)


async def _pin_message(message: discord.Message, reason: str) -> bool:
    """Pin a message, handling capacity and errors. Returns True on success."""
    if message.pinned:
        return False

    await _ensure_pin_capacity(message.channel)

    try:
        await message.pin(reason=reason)
        log.info(
            "Pinned message %s in #%s (%s)",
            message.id,
            message.channel.name,
            reason,
        )
        return True
    except discord.Forbidden:
        log.warning("Missing permission to pin in #%s", message.channel.name)
        return False
    except discord.HTTPException:
        log.exception("Failed to pin message %s in #%s", message.id, message.channel.name)
        return False


# ---------------------------------------------------------------------------
# Event handlers (called from bot.py)
# ---------------------------------------------------------------------------


async def handle_announcement_pin(message: discord.Message) -> None:
    """Auto-pin new messages posted to #announcements."""
    if message.channel.name != ANNOUNCEMENTS_CHANNEL:
        return

    await _pin_message(message, "Auto-pin: announcement post")


def _is_moderator(member: discord.Member) -> bool:
    """Check if a guild member has a moderator role."""
    return any(role.name in MODERATOR_ROLES for role in member.roles)


async def handle_reaction_pin(
    payload: discord.RawReactionActionEvent,
    guild: discord.Guild,
) -> None:
    """Handle reaction adds for pin-emoji and threshold-based pinning.

    Called from on_raw_reaction_add in bot.py.
    """
    channel = guild.get_channel(payload.channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        log.warning("Could not fetch message %s in #%s", payload.message_id, channel.name)
        return

    if message.pinned:
        return

    emoji_str = str(payload.emoji)

    # --- Moderator pin-emoji trigger ---
    if emoji_str == PIN_EMOJI:
        member = payload.member or guild.get_member(payload.user_id)
        if member and _is_moderator(member):
            await _pin_message(message, f"Moderator pin by {member.display_name}")
            return

    # --- Reaction threshold trigger ---
    total_reactions = sum(r.count for r in message.reactions)
    if total_reactions >= PIN_REACTION_THRESHOLD:
        await _pin_message(message, f"Reaction threshold ({total_reactions} reactions)")
