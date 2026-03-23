"""TradeArena Community Manager Discord Bot.

Core responsibilities:
- Answer SDK/installation/setup questions in #bot-help using TradeArena docs
- Welcome new members in #introductions
- Basic moderation (spam detection)
- Escalate well-structured bug reports from #bug-reports to Paperclip issues
- Post daily leaderboard updates to #announcements
- Post changelog entries from GitHub releases to #announcements

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
from datetime import UTC, datetime, time

import discord
import httpx
from discord import Intents, Member, Message
from discord.ext import tasks

from services.discord_bot.knowledge import (
    build_context_prompt,
    load_knowledge_base,
    load_readme,
)
from services.discord_bot.paperclip import PaperclipClient
from services.discord_bot.pins import handle_announcement_pin, handle_reaction_pin
from services.discord_bot.roles import sync_contributor_roles, sync_rank_roles
from services.discord_bot.setup import setup_server
from services.discord_bot.welcome import post_welcome_and_rules

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
ANNOUNCEMENTS_CHANNEL = "announcements"

# TradeArena API for leaderboard
TRADEARENA_API_URL = os.getenv("TRADEARENA_API_URL", "http://localhost:8000").rstrip("/")

# GitHub repo for changelog polling
GITHUB_REPO = os.getenv("GITHUB_REPO", "luxman89/TradeArena")
CHANGELOG_CHECK_MINUTES = 30  # Poll interval for new releases

# Leaderboard post time — daily at 12:00 UTC
LEADERBOARD_POST_TIME = time(hour=12, minute=0, tzinfo=UTC)

# Role sync runs right after leaderboard (12:05 UTC) to use fresh data
ROLE_SYNC_TIME = time(hour=12, minute=5, tzinfo=UTC)

# Contributor role check interval (minutes)
CONTRIBUTOR_CHECK_MINUTES = 60

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

# ---------------------------------------------------------------------------
# Paperclip client (initialized once at startup)
# ---------------------------------------------------------------------------

_paperclip = PaperclipClient()


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
intents.reactions = True

client = discord.Client(intents=intents)

# Simple per-user message tracking for spam detection
_recent_messages: dict[int, list[str]] = {}  # user_id -> last N messages

# Track last leaderboard post to avoid duplicates
_last_leaderboard_post: datetime | None = None

# Track the last changelog release tag we posted to avoid duplicates
_last_changelog_tag: str | None = None


@client.event
async def on_ready() -> None:
    log.info("Bot connected as %s (id=%s)", client.user, client.user.id if client.user else "?")
    log.info("Serving %d guilds", len(client.guilds))
    _init_knowledge()

    # Auto-setup: create missing channels/roles and post welcome/rules
    for guild in client.guilds:
        try:
            await setup_server(guild)
            await post_welcome_and_rules(guild)
        except Exception:
            log.exception("Server setup failed for guild: %s", guild.name)

    if not post_leaderboard.is_running():
        post_leaderboard.start()
        log.info("Leaderboard scheduled task started (daily at %s)", LEADERBOARD_POST_TIME)
    if not check_changelog.is_running():
        check_changelog.start()
        log.info("Changelog check started (every %d minutes)", CHANGELOG_CHECK_MINUTES)
    if not sync_roles.is_running():
        sync_roles.start()
        log.info("Role sync scheduled task started (daily at %s)", ROLE_SYNC_TIME)
    if not check_contributors.is_running():
        check_contributors.start()
        log.info("Contributor check started (every %d minutes)", CONTRIBUTOR_CHECK_MINUTES)


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

    # --- #announcements: auto-pin new posts ---
    if message.channel.name == ANNOUNCEMENTS_CHANNEL:
        await handle_announcement_pin(message)
        return


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    """Handle reaction adds for auto-pinning (threshold and moderator pin emoji)."""
    if payload.guild_id is None:
        return
    guild = client.get_guild(payload.guild_id)
    if guild is None:
        return
    # Ignore bot's own reactions
    if client.user and payload.user_id == client.user.id:
        return
    await handle_reaction_pin(payload, guild)


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


def _extract_bug_title(content: str) -> str:
    """Extract a concise title from bug report content.

    Uses the first non-empty line (up to 100 chars), or a generic prefix.
    """
    for line in content.split("\n"):
        line = line.strip().lstrip("#").strip()
        if len(line) >= 10:
            title = line[:100]
            if len(line) > 100:
                title += "..."
            return title
    return "Bug report from Discord"


def _build_issue_description(message: Message) -> str:
    """Format a Paperclip issue description from a Discord bug report."""
    author = message.author.display_name
    channel_url = ""
    if message.guild and hasattr(message, "jump_url"):
        channel_url = message.jump_url

    parts = [
        f"**Reported by:** {author} (Discord)",
    ]
    if channel_url:
        parts.append(f"**Source:** [Discord message]({channel_url})")
    parts.append(f"\n---\n\n{message.content.strip()}")
    return "\n".join(parts)


async def _handle_bug_report(message: Message) -> None:
    """Acknowledge bug reports and escalate to Paperclip when well-structured."""
    content = message.content.strip()
    if len(content) < 20:
        return

    # Only respond if it looks like a bug report (not a reply/conversation)
    if message.reference:  # skip replies
        return

    # Check if the report has sufficient detail for escalation
    detail_keywords = ["steps", "reproduce", "expected", "actual", "error", "traceback"]
    has_detail = sum(1 for kw in detail_keywords if kw in content.lower())

    if has_detail >= 2:
        # Well-structured report — escalate to Paperclip
        await message.add_reaction("✅")

        if _paperclip.configured:
            title = _extract_bug_title(content)
            description = _build_issue_description(message)
            issue = await _paperclip.create_issue(
                title=f"[Discord Bug] {title}",
                description=description,
                priority="medium",
            )
            if issue:
                await message.add_reaction("🎫")
                await message.reply(
                    f"Thanks for the detailed bug report! I've created a tracking issue: "
                    f"**{issue.identifier}**\n"
                    f"The engineering team will investigate.",
                    mention_author=False,
                )
                log.info(
                    "Escalated bug report from %s to Paperclip issue %s",
                    message.author.display_name,
                    issue.identifier,
                )
                return

        # Paperclip not configured or creation failed — fall back to acknowledgement
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
# Leaderboard updates
# ---------------------------------------------------------------------------

RANK_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


async def fetch_leaderboard(limit: int = 10) -> list[dict] | None:
    """Fetch top creators from the TradeArena leaderboard API."""
    url = f"{TRADEARENA_API_URL}/leaderboard?limit={limit}"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            data = resp.json()
            return data.get("entries", [])
    except Exception:
        log.exception("Failed to fetch leaderboard")
        return None


def build_leaderboard_embed(entries: list[dict]) -> discord.Embed:
    """Format leaderboard entries into a Discord embed."""
    embed = discord.Embed(
        title="📊 TradeArena Leaderboard",
        description="Daily top traders ranked by composite score",
        color=0x00B4D8,
        timestamp=datetime.now(UTC),
    )

    if not entries:
        embed.add_field(name="No data", value="No traders on the leaderboard yet.")
        return embed

    lines = []
    for i, entry in enumerate(entries, start=1):
        medal = RANK_MEDALS.get(i, f"**{i}.**")
        name = entry.get("display_name", "Unknown")
        score = entry.get("composite_score", 0.0)
        win_rate = entry.get("win_rate", 0.0)
        total = entry.get("total_signals", 0)
        lines.append(f"{medal} **{name}** — {score:.2f} (WR: {win_rate:.0%} · {total} signals)")

    embed.add_field(
        name="Top Traders",
        value="\n".join(lines),
        inline=False,
    )
    embed.set_footer(text="Updated daily at 12:00 UTC • tradearena.io")
    return embed


@tasks.loop(time=LEADERBOARD_POST_TIME)
async def post_leaderboard() -> None:
    """Scheduled task: post leaderboard to #announcements daily."""
    global _last_leaderboard_post

    now = datetime.now(UTC)
    if _last_leaderboard_post and (now - _last_leaderboard_post).total_seconds() < 3600:
        log.info("Skipping leaderboard post — last post was at %s", _last_leaderboard_post)
        return

    entries = await fetch_leaderboard(limit=10)
    if entries is None:
        log.warning("Leaderboard fetch failed — skipping post")
        return

    for guild in client.guilds:
        channel = discord.utils.get(guild.text_channels, name=ANNOUNCEMENTS_CHANNEL)
        if not channel:
            log.warning("No #%s channel in %s", ANNOUNCEMENTS_CHANNEL, guild.name)
            continue

        embed = build_leaderboard_embed(entries)
        try:
            await channel.send(embed=embed)
            _last_leaderboard_post = now
            log.info("Posted leaderboard update to #%s in %s", ANNOUNCEMENTS_CHANNEL, guild.name)
        except discord.Forbidden:
            log.error("Missing permission to send in #%s in %s", ANNOUNCEMENTS_CHANNEL, guild.name)


@post_leaderboard.before_loop
async def _wait_until_ready() -> None:
    await client.wait_until_ready()


# ---------------------------------------------------------------------------
# Changelog posting — GitHub release polling
# ---------------------------------------------------------------------------


async def fetch_latest_release() -> dict | None:
    """Fetch the latest release from the GitHub API."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception:
        log.exception("Failed to fetch latest GitHub release")
        return None


def build_changelog_embed(release: dict) -> discord.Embed:
    """Format a GitHub release into a Discord embed for #announcements."""
    tag = release.get("tag_name", "unknown")
    name = release.get("name") or tag
    body = release.get("body", "") or ""
    html_url = release.get("html_url", "")
    published = release.get("published_at", "")

    # Trim body to fit Discord embed limits (max 4096 for description)
    if len(body) > 2000:
        body = body[:1997] + "..."

    embed = discord.Embed(
        title=f"🚀 New Release: {name}",
        description=body or "No release notes provided.",
        color=0x2ECC71,  # Green
        url=html_url,
    )
    embed.add_field(name="Version", value=f"`{tag}`", inline=True)

    if html_url:
        embed.add_field(
            name="Full Changelog",
            value=f"[View on GitHub]({html_url})",
            inline=True,
        )

    if published:
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            embed.timestamp = pub_dt
        except ValueError:
            pass

    embed.set_footer(text=f"{GITHUB_REPO} • GitHub Releases")
    return embed


@tasks.loop(minutes=CHANGELOG_CHECK_MINUTES)
async def check_changelog() -> None:
    """Poll GitHub for new releases and post to #announcements."""
    global _last_changelog_tag

    release = await fetch_latest_release()
    if release is None:
        return

    tag = release.get("tag_name")
    if not tag:
        return

    # On first run, record the current tag without posting (avoid re-posting old releases)
    if _last_changelog_tag is None:
        _last_changelog_tag = tag
        log.info("Initialized changelog tracker with tag: %s", tag)
        return

    # Skip if we already posted this tag
    if tag == _last_changelog_tag:
        return

    _last_changelog_tag = tag
    log.info("New release detected: %s", tag)

    embed = build_changelog_embed(release)
    for guild in client.guilds:
        channel = discord.utils.get(guild.text_channels, name=ANNOUNCEMENTS_CHANNEL)
        if not channel:
            log.warning("No #%s channel in %s", ANNOUNCEMENTS_CHANNEL, guild.name)
            continue
        try:
            await channel.send(embed=embed)
            log.info("Posted changelog for %s to #%s in %s", tag, ANNOUNCEMENTS_CHANNEL, guild.name)
        except discord.Forbidden:
            log.error("Missing permission to send in #%s in %s", ANNOUNCEMENTS_CHANNEL, guild.name)


@check_changelog.before_loop
async def _wait_changelog_ready() -> None:
    await client.wait_until_ready()


# ---------------------------------------------------------------------------
# Role management — rank sync and contributor check
# ---------------------------------------------------------------------------


@tasks.loop(time=ROLE_SYNC_TIME)
async def sync_roles() -> None:
    """Scheduled task: sync Elite Trader / Pro Trader roles based on leaderboard."""
    for guild in client.guilds:
        try:
            changes = await sync_rank_roles(guild)
            total = len(changes["added"]) + len(changes["removed"])
            if total > 0:
                log.info(
                    "Rank role sync in %s: %d added, %d removed",
                    guild.name,
                    len(changes["added"]),
                    len(changes["removed"]),
                )
        except Exception:
            log.exception("Error syncing rank roles in %s", guild.name)


@sync_roles.before_loop
async def _wait_sync_roles_ready() -> None:
    await client.wait_until_ready()


@tasks.loop(minutes=CONTRIBUTOR_CHECK_MINUTES)
async def check_contributors() -> None:
    """Scheduled task: assign Contributor role to members with merged PRs."""
    for guild in client.guilds:
        try:
            changes = await sync_contributor_roles(guild)
            if changes["added"]:
                log.info(
                    "Contributor role sync in %s: assigned to %s",
                    guild.name,
                    ", ".join(changes["added"]),
                )
        except Exception:
            log.exception("Error syncing contributor roles in %s", guild.name)


@check_contributors.before_loop
async def _wait_contributors_ready() -> None:
    await client.wait_until_ready()


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
