"""Onboarding email drip sequence — SendGrid transactional emails.

4-email sequence triggered by user registration:
  Day 0: Welcome + quickstart
  Day 1: First score explainer + leaderboard link
  Day 3: Battle invite CTA
  Day 7: Weekly recap + referral prompt

Emails are tracked in the email_events table for open/click analytics
and CAN-SPAM compliant unsubscribe handling.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import httpx

logger = logging.getLogger(__name__)

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "noreply@tradearena.app")
SENDGRID_FROM_NAME = os.getenv("SENDGRID_FROM_NAME", "TradeArena")
BASE_URL = os.getenv("BASE_URL", "https://tradearena.app")

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class EmailStep(StrEnum):
    WELCOME = "welcome"  # Day 0
    FIRST_SCORE = "first_score"  # Day 1
    BATTLE_INVITE = "battle_invite"  # Day 3
    WEEKLY_RECAP = "weekly_recap"  # Day 7


# Schedule: (step, delay from registration)
DRIP_SCHEDULE: list[tuple[EmailStep, timedelta]] = [
    (EmailStep.WELCOME, timedelta(minutes=0)),
    (EmailStep.FIRST_SCORE, timedelta(days=1)),
    (EmailStep.BATTLE_INVITE, timedelta(days=3)),
    (EmailStep.WEEKLY_RECAP, timedelta(days=7)),
]


def generate_unsubscribe_token() -> str:
    """Generate a cryptographically secure unsubscribe token."""
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def _unsubscribe_url(token: str) -> str:
    return f"{BASE_URL}/email/unsubscribe?token={token}"


def _tracking_pixel_url(event_id: str) -> str:
    return f"{BASE_URL}/email/open/{event_id}"


def _click_url(event_id: str, dest: str) -> str:
    return f"{BASE_URL}/email/click/{event_id}?url={dest}"


# ---------------------------------------------------------------------------
# HTML email templates
# ---------------------------------------------------------------------------

_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 0; background: #0a0a0a; color: #e0e0e0; }
  .container { max-width: 600px; margin: 0 auto; padding: 32px 24px; }
  .header { text-align: center; padding: 24px 0; border-bottom: 1px solid #222; }
  .header h1 { color: #00ff88; font-size: 28px; margin: 0; }
  .content { padding: 24px 0; line-height: 1.6; }
  .cta { display: inline-block; background: #00ff88; color: #0a0a0a; font-weight: 700;
         padding: 14px 32px; border-radius: 8px; text-decoration: none; margin: 16px 0; }
  .cta:hover { background: #00cc6a; }
  .footer { border-top: 1px solid #222; padding: 16px 0; font-size: 12px; color: #666;
            text-align: center; }
  .footer a { color: #888; }
  h2 { color: #fff; }
  .highlight { color: #00ff88; font-weight: 600; }
  .card { background: #111; border: 1px solid #222; border-radius: 8px; padding: 16px;
          margin: 16px 0; }
  .score-dim { display: inline-block; margin: 4px 8px; }
</style>
"""


def _wrap(body_html: str, unsub_url: str, event_id: str) -> str:
    pixel = _tracking_pixel_url(event_id)
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
{_STYLE}</head>
<body>
<div class="container">
  <div class="header"><h1>TradeArena</h1></div>
  <div class="content">{body_html}</div>
  <div class="footer">
    <p>TradeArena — Trustless trading signal competitions</p>
    <p><a href="{unsub_url}">Unsubscribe</a> from these emails</p>
  </div>
</div>
<img src="{pixel}" width="1" height="1" alt="" style="display:none" />
</body></html>"""


def _welcome_body(display_name: str, event_id: str) -> tuple[str, str, str]:
    """Returns (subject, plain_text, html)."""
    subject = f"Welcome to TradeArena, {display_name}!"
    arena_link = _click_url(event_id, f"{BASE_URL}/arena")
    docs_link = _click_url(event_id, f"{BASE_URL}/docs")
    body = f"""
    <h2>Welcome to the arena, {display_name}.</h2>
    <p>You just joined a platform where every trading call is
    <span class="highlight">cryptographically committed</span> before the market moves.
    No hindsight edits. No deleted tweets. Just skill.</p>

    <div class="card">
      <h3>Submit your first signal in 5 minutes</h3>
      <p>1. Grab your API key from your registration response<br>
         2. Pick an asset (BTC, ETH, SOL, ...)<br>
         3. Call <code>POST /signal</code> with your prediction<br>
         4. Watch the oracle resolve it automatically</p>
    </div>

    <p style="text-align: center">
      <a href="{arena_link}" class="cta">Open the Arena</a>
    </p>
    <p style="text-align: center; font-size: 14px; color: #888;">
      or check the <a href="{docs_link}" style="color: #00ff88">API docs</a>
      to integrate your bot
    </p>
    """
    plain = (
        f"Welcome to TradeArena, {display_name}!\n\n"
        "Submit your first signal in 5 minutes:\n"
        "1. Use your API key\n2. Pick an asset\n"
        f"3. POST /signal\n\nOpen the arena: {BASE_URL}/arena"
    )
    return subject, plain, body


def _first_score_body(display_name: str, event_id: str) -> tuple[str, str, str]:
    subject = f"{display_name}, your first score is in"
    lb_link = _click_url(event_id, f"{BASE_URL}/leaderboard")
    body = f"""
    <h2>Your scores are live.</h2>
    <p>Every signal you submit gets scored across four dimensions:</p>

    <div class="card">
      <span class="score-dim"><span class="highlight">30%</span> Win Rate</span>
      <span class="score-dim"><span class="highlight">30%</span> Risk-Adjusted Return</span>
      <span class="score-dim"><span class="highlight">25%</span> Consistency</span>
      <span class="score-dim"><span class="highlight">15%</span> Calibration</span>
    </div>

    <p>The oracle resolves signals automatically using live market data.
    No self-reporting. No cherry-picking.</p>

    <p>As you submit more signals, your composite score improves and you
    climb the leaderboard. XP unlocks new avatars and titles.</p>

    <p style="text-align: center">
      <a href="{lb_link}" class="cta">Check the Leaderboard</a>
    </p>
    """
    plain = (
        f"Hey {display_name},\n\n"
        "Your scores are live! Every signal is scored across 4 dimensions:\n"
        "Win Rate (30%), Risk-Adjusted Return (30%), Consistency (25%), "
        f"Calibration (15%).\n\nCheck the leaderboard: {BASE_URL}/leaderboard"
    )
    return subject, plain, body


def _battle_invite_body(display_name: str, event_id: str) -> tuple[str, str, str]:
    subject = f"{display_name}, ready for your first battle?"
    arena_link = _click_url(event_id, f"{BASE_URL}/arena")
    body = f"""
    <h2>Ready for your first battle?</h2>
    <p>Battles are head-to-head showdowns where two traders compete
    over a fixed window. Same market, same timeframe — best signals win.</p>

    <div class="card">
      <h3>How battles work</h3>
      <p>1. Challenge another creator (or get auto-matched)<br>
         2. Both submit signals during the battle window<br>
         3. The oracle scores both sets of signals<br>
         4. Winner takes the glory (and the XP)</p>
    </div>

    <p>The matchmaker runs weekly to pair creators of similar skill.
    Or you can challenge anyone directly.</p>

    <p style="text-align: center">
      <a href="{arena_link}" class="cta">Start a Battle</a>
    </p>
    """
    plain = (
        f"Hey {display_name},\n\n"
        "Ready for your first battle? Challenge another creator to a "
        "head-to-head signal competition.\n\n"
        f"Start a battle: {BASE_URL}/arena"
    )
    return subject, plain, body


def _weekly_recap_body(display_name: str, event_id: str) -> tuple[str, str, str]:
    subject = f"{display_name}, your first week on TradeArena"
    lb_link = _click_url(event_id, f"{BASE_URL}/leaderboard")
    arena_link = _click_url(event_id, f"{BASE_URL}/arena")
    body = f"""
    <h2>Your first week in review.</h2>
    <p>You've been on TradeArena for a week now. Here's what matters next:</p>

    <div class="card">
      <h3>Keep the momentum</h3>
      <p>Consistency is 25% of your composite score.
      Regular, well-reasoned signals beat sporadic hot takes.</p>
    </div>

    <div class="card">
      <h3>Invite your crew</h3>
      <p>Know someone who thinks they can trade?
      Share your profile link and let the signals do the talking.</p>
    </div>

    <p style="text-align: center">
      <a href="{lb_link}" class="cta">See Your Ranking</a>
    </p>
    <p style="text-align: center; font-size: 14px; color: #888;">
      <a href="{arena_link}" style="color: #00ff88">Back to the arena</a>
    </p>
    """
    plain = (
        f"Hey {display_name},\n\n"
        "Your first week on TradeArena! Consistency is 25% of your score — "
        "keep submitting quality signals.\n\n"
        "Know someone who can trade? Share your profile link.\n\n"
        f"See your ranking: {BASE_URL}/leaderboard"
    )
    return subject, plain, body


_TEMPLATE_MAP = {
    EmailStep.WELCOME: _welcome_body,
    EmailStep.FIRST_SCORE: _first_score_body,
    EmailStep.BATTLE_INVITE: _battle_invite_body,
    EmailStep.WEEKLY_RECAP: _weekly_recap_body,
}


def render_email(
    step: EmailStep, display_name: str, unsub_token: str, event_id: str
) -> tuple[str, str, str]:
    """Render an email for the given step. Returns (subject, plain_text, html)."""
    builder = _TEMPLATE_MAP[step]
    subject, plain, body_html = builder(display_name, event_id)
    unsub_url = _unsubscribe_url(unsub_token)
    html = _wrap(body_html, unsub_url, event_id)
    return subject, plain, html


async def send_email(
    to_email: str,
    subject: str,
    plain_text: str,
    html_content: str,
    unsub_token: str,
) -> bool:
    """Send an email via SendGrid API. Returns True on success."""
    if not SENDGRID_API_KEY:
        logger.warning("SENDGRID_API_KEY not set — email not sent to %s", to_email)
        return False

    unsub_url = _unsubscribe_url(unsub_token)
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": SENDGRID_FROM_EMAIL, "name": SENDGRID_FROM_NAME},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain_text},
            {"type": "text/html", "value": html_content},
        ],
        "headers": {
            "List-Unsubscribe": f"<{unsub_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": False},
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SENDGRID_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    if resp.status_code in (200, 201, 202):
        logger.info("Email sent: %s -> %s", subject, to_email)
        return True
    else:
        logger.error(
            "SendGrid error %d: %s (to=%s, subject=%s)",
            resp.status_code,
            resp.text,
            to_email,
            subject,
        )
        return False


def get_due_emails(
    registered_at: datetime,
    sent_steps: set[str],
    now: datetime | None = None,
) -> list[EmailStep]:
    """Return email steps that are due but not yet sent."""
    if now is None:
        now = datetime.now(UTC)
    due = []
    for step, delay in DRIP_SCHEDULE:
        if step.value in sent_steps:
            continue
        if now >= registered_at + delay:
            due.append(step)
    return due
