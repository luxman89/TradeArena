"""Post and pin welcome message and rules from docs/community/welcome-and-rules.md.

On bot startup, checks #rules and #announcements for existing pinned messages.
If no welcome/rules content has been pinned yet, posts and pins them.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import discord

log = logging.getLogger("tradearena.bot.welcome")

RULES_CHANNEL = "rules"

# Marker text to detect if we already posted the rules
_RULES_MARKER = "**Welcome to TradeArena!**"


def _load_welcome_and_rules() -> tuple[str, str]:
    """Load welcome message and rules from the docs file.

    Returns (welcome_message, rules_text).
    """
    for candidate in [
        Path(__file__).resolve().parent.parent.parent / "docs/community/welcome-and-rules.md",
        Path("/opt/tradearena/docs/community/welcome-and-rules.md"),
    ]:
        if candidate.is_file():
            content = candidate.read_text(encoding="utf-8")
            break
    else:
        log.warning("welcome-and-rules.md not found")
        return "", ""

    # Split into welcome and rules sections
    parts = re.split(r"^## Server Rules", content, flags=re.MULTILINE)
    welcome = ""
    rules = ""

    # Extract the welcome blockquote
    welcome_match = re.search(r"(> .+(?:\n> .+)*)", parts[0], re.DOTALL)
    if welcome_match:
        # Convert blockquote to plain text for Discord
        lines = welcome_match.group(1).split("\n")
        welcome = "\n".join(line.lstrip("> ").rstrip() for line in lines)

    if len(parts) > 1:
        rules = "## Server Rules\n" + parts[1].strip()

    return welcome.strip(), rules.strip()


async def _has_bot_pin(channel: discord.TextChannel, marker: str) -> bool:
    """Check if the bot already has a pinned message containing the marker."""
    try:
        pins = await channel.pins()
        for pin in pins:
            if pin.author.bot and marker in pin.content:
                return True
    except discord.Forbidden:
        log.warning("Missing permission to read pins in #%s", channel.name)
    return False


async def post_welcome_and_rules(guild: discord.Guild) -> None:
    """Post and pin welcome message + rules in #rules if not already present."""
    rules_channel = discord.utils.get(guild.text_channels, name=RULES_CHANNEL)
    if not rules_channel:
        log.warning("No #%s channel found in %s", RULES_CHANNEL, guild.name)
        return

    # Check if we already posted
    if await _has_bot_pin(rules_channel, _RULES_MARKER):
        log.info("Welcome/rules already pinned in #%s — skipping", RULES_CHANNEL)
        return

    welcome, rules = _load_welcome_and_rules()
    if not welcome and not rules:
        log.warning("No welcome/rules content to post")
        return

    try:
        # Post welcome message
        if welcome:
            welcome_msg = await rules_channel.send(welcome)
            try:
                await welcome_msg.pin(reason="TradeArena welcome message")
                log.info("Pinned welcome message in #%s", RULES_CHANNEL)
            except discord.Forbidden:
                log.error("Missing permission to pin in #%s", RULES_CHANNEL)

        # Post rules (may need to split if > 2000 chars)
        if rules:
            chunks = _split_message(rules, max_len=2000)
            for i, chunk in enumerate(chunks):
                rules_msg = await rules_channel.send(chunk)
                if i == 0:
                    try:
                        await rules_msg.pin(reason="TradeArena server rules")
                        log.info("Pinned rules in #%s", RULES_CHANNEL)
                    except discord.Forbidden:
                        log.error("Missing permission to pin in #%s", RULES_CHANNEL)

    except discord.Forbidden:
        log.error("Missing permission to send in #%s", RULES_CHANNEL)


def _split_message(text: str, max_len: int = 2000) -> list[str]:
    """Split a message into chunks respecting Discord's 2000 char limit.

    Tries to split at newlines rather than mid-sentence.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find the last newline within the limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
