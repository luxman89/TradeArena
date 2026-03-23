"""TradeArena Community Manager Discord Bot.

Core responsibilities (Phase 1):
- Answer SDK/installation/setup questions in #bot-help using TradeArena docs
- Welcome new members in #introductions
- Basic moderation (spam detection)

Usage:
    DISCORD_BOT_TOKEN=... python -m services.discord_bot.bot
    # or
    DISCORD_BOT_TOKEN=... python services/discord_bot/bot.py
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import UTC, datetime

import discord
from discord import Intents, Member, Message

from services.discord_bot.knowledge import (
    build_context_prompt,
    load_knowledge_base,
    load_readme,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tradearena.bot")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_HELP_CHANNEL = "bot-help"
INTRODUCTIONS_CHANNEL = "introductions"
BUG_REPORTS_CHANNEL = "bug-reports"

# Spam thresholds
SPAM_REPEAT_THRESHOLD = 3  # same message N times in a row
SPAM_LINK_PATTERN = re.compile(
    r"(discord\.gg/|bit\.ly/|t\.me/|click\s+here|free\s+signals?|join\s+my\s+group)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Knowledge base (loaded once at startup)
# ---------------------------------------------------------------------------

_knowledge: dict[str, str] = {}
_context_prompt: str = ""


def _init_knowledge() -> None:
    global _knowledge, _context_prompt
    _knowledge = load_knowledge_base()
    readme = load_readme()
    if readme:
        _knowledge["README.md"] = readme
    _context_prompt = build_context_prompt(_knowledge)
    log.info("Loaded %d docs into knowledge base", len(_knowledge))


# ---------------------------------------------------------------------------
# Answer engine — keyword matching against docs
# ---------------------------------------------------------------------------


def find_answer(question: str) -> str:
    """Search the knowledge base for relevant content.

    Uses simple keyword matching. Returns the most relevant excerpt or a
    fallback message. This avoids an external LLM dependency for Phase 1.
    """
    question_lower = question.lower().strip()
    words = set(re.findall(r"\w+", question_lower))
    # Remove common stop words
    stop = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "how",
        "what",
        "why",
        "when",
        "where",
        "can",
        "i",
        "my",
        "me",
        "to",
        "in",
        "on",
        "it",
        "of",
        "and",
        "or",
        "for",
        "with",
        "this",
        "that",
        "be",
    }
    keywords = words - stop
    if not keywords:
        return ""

    best_score = 0
    best_section = ""

    for _path, content in _knowledge.items():
        # Split into sections by ## headings
        sections = re.split(r"(?=^#{1,3}\s)", content, flags=re.MULTILINE)
        for section in sections:
            section_lower = section.lower()
            score = sum(1 for kw in keywords if kw in section_lower)
            # Boost for exact phrase matches
            if question_lower[:30] in section_lower:
                score += 3
            if score > best_score:
                best_score = score
                best_section = section.strip()

    if best_score < 2 or not best_section:
        return ""

    # Trim to reasonable length
    if len(best_section) > 1500:
        best_section = best_section[:1500] + "..."

    return best_section


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# Simple per-user message tracking for spam detection
_recent_messages: dict[int, list[str]] = {}  # user_id -> last N messages


@client.event
async def on_ready() -> None:
    log.info("Bot connected as %s (id=%s)", client.user, client.user.id if client.user else "?")
    log.info("Serving %d guilds", len(client.guilds))
    _init_knowledge()


@client.event
async def on_member_join(member: Member) -> None:
    """Welcome new members in #introductions."""
    guild = member.guild
    channel = discord.utils.get(guild.text_channels, name=INTRODUCTIONS_CHANNEL)
    if not channel:
        log.warning("No #%s channel found in %s", INTRODUCTIONS_CHANNEL, guild.name)
        return

    welcome_msg = (
        f"Welcome to TradeArena, {member.mention}! 👋\n\n"
        f"Here's how to get started:\n"
        f"1. Read the rules in #rules\n"
        f"2. Introduce yourself and your bot here\n"
        f"3. Install the SDK: `pip install tradearena`\n"
        f"4. Submit your first signal and join the leaderboard!\n\n"
        f"Need help? Ask in #bot-help. Happy trading!"
    )
    try:
        await channel.send(welcome_msg)
        log.info("Welcomed new member: %s", member.display_name)
    except discord.Forbidden:
        log.error("Missing permission to send in #%s", INTRODUCTIONS_CHANNEL)


@client.event
async def on_message(message: Message) -> None:
    # Ignore own messages
    if message.author == client.user:
        return
    # Ignore DMs
    if not message.guild:
        return

    # --- Spam detection ---
    if await _check_spam(message):
        return

    # --- #bot-help: answer questions ---
    if message.channel.name == BOT_HELP_CHANNEL:
        await _handle_bot_help(message)
        return

    # --- #bug-reports: acknowledge and guide ---
    if message.channel.name == BUG_REPORTS_CHANNEL:
        await _handle_bug_report(message)
        return


async def _check_spam(message: Message) -> bool:
    """Basic spam detection. Returns True if message was flagged as spam."""
    content = message.content.strip()
    if not content:
        return False

    # Check for suspicious links / promo patterns
    if SPAM_LINK_PATTERN.search(content):
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} Your message was removed for containing "
                f"promotional content. Please review the server rules in #rules.",
                delete_after=15,
            )
            log.info("Deleted spam from %s: %s", message.author, content[:100])
            return True
        except discord.Forbidden:
            log.warning("Missing permission to delete spam message")

    # Check for repeated messages
    user_id = message.author.id
    history = _recent_messages.setdefault(user_id, [])
    history.append(content)
    if len(history) > SPAM_REPEAT_THRESHOLD + 2:
        _recent_messages[user_id] = history[-(SPAM_REPEAT_THRESHOLD + 2) :]
        history = _recent_messages[user_id]

    if len(history) >= SPAM_REPEAT_THRESHOLD:
        recent = history[-SPAM_REPEAT_THRESHOLD:]
        if all(m == recent[0] for m in recent):
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} Please don't spam. "
                    f"Your repeated message was removed.",
                    delete_after=15,
                )
                log.info("Deleted repeated spam from %s", message.author)
                return True
            except discord.Forbidden:
                pass

    return False


async def _handle_bot_help(message: Message) -> None:
    """Answer questions in #bot-help using the knowledge base."""
    content = message.content.strip()
    if len(content) < 5:
        return

    # Don't respond to messages that are clearly conversations (no question marks,
    # short replies like "thanks", "ok", etc.)
    is_question = (
        "?" in content
        or content.lower().startswith(("how", "what", "why", "where", "can", "does", "is"))
        or any(
            kw in content.lower()
            for kw in ["help", "install", "error", "issue", "signal", "sdk", "api", "setup"]
        )
    )
    if not is_question:
        return

    async with message.channel.typing():
        answer = find_answer(content)

    if answer:
        # Format the response
        response = f"**Here's what I found:**\n\n{answer}"
        if len(response) > 2000:
            response = response[:1997] + "..."
        await message.reply(response, mention_author=False)
    else:
        await message.reply(
            "I couldn't find a specific answer to that in the docs. "
            "Try checking:\n"
            "- **FAQ:** <https://github.com/luxman89/TradeArena#readme>\n"
            "- **GitHub Issues:** <https://github.com/luxman89/TradeArena/issues>\n\n"
            "Or ask in #general — someone from the community might know!",
            mention_author=False,
        )


async def _handle_bug_report(message: Message) -> None:
    """Acknowledge bug reports and remind about the template."""
    content = message.content.strip()
    if len(content) < 20:
        return

    # Only respond if it looks like a bug report (not a reply/conversation)
    if message.reference:  # skip replies
        return

    # Check if the report has basic structure
    has_steps = any(
        kw in content.lower()
        for kw in ["steps", "reproduce", "expected", "actual", "error", "traceback"]
    )

    if has_steps:
        await message.add_reaction("✅")
        await message.reply(
            "Thanks for the detailed bug report! The engineering team will look into this.",
            mention_author=False,
        )
    else:
        await message.reply(
            "Thanks for reporting! To help us fix this faster, please include:\n"
            "- **Steps to reproduce**\n"
            "- **Expected behavior**\n"
            "- **Actual behavior**\n"
            "- **Error logs** (if any)\n\n"
            "You can also open a GitHub issue: "
            "<https://github.com/luxman89/TradeArena/issues>",
            mention_author=False,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        log.error("DISCORD_BOT_TOKEN environment variable is not set")
        sys.exit(1)

    log.info("Starting TradeArena Community Manager bot...")
    log.info("Timestamp: %s", datetime.now(UTC).isoformat())
    client.run(token, log_handler=None)


if __name__ == "__main__":
    main()
