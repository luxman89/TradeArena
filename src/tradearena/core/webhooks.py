"""Webhook delivery engine — fire-and-forget with HMAC signing and one retry."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRY_DELAY_SECONDS = 30
DELIVERY_TIMEOUT_SECONDS = 10


def _compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload verification."""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


async def _deliver(url: str, payload: dict[str, Any], secret: str) -> bool:
    """POST JSON payload to webhook URL with HMAC signature header.

    Returns True on success (2xx), False otherwise.
    """
    body = json.dumps(payload, default=str, sort_keys=True)
    body_bytes = body.encode()
    signature = _compute_signature(body_bytes, secret)

    headers = {
        "Content-Type": "application/json",
        "X-TradeArena-Signature": f"sha256={signature}",
        "X-TradeArena-Event": payload.get("event", "unknown"),
    }

    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, content=body_bytes, headers=headers)
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("Webhook delivery to %s returned %d", url, resp.status_code)
        return False
    except Exception:
        logger.warning("Webhook delivery to %s failed", url, exc_info=True)
        return False


async def deliver_webhook(
    url: str,
    event: str,
    data: dict[str, Any],
    secret: str,
) -> None:
    """Deliver a webhook event with one retry after 30s on failure.

    Fire-and-forget — failures are logged but never raise.
    """
    payload = {
        "event": event,
        "data": data,
        "timestamp": time.time(),
    }

    ok = await _deliver(url, payload, secret)
    if ok:
        return

    # Retry once after delay
    await asyncio.sleep(RETRY_DELAY_SECONDS)
    ok = await _deliver(url, payload, secret)
    if not ok:
        logger.error("Webhook delivery to %s failed after retry (event=%s)", url, event)


async def fire_webhook_for_creator(
    db_session,
    creator_id: str,
    event: str,
    data: dict[str, Any],
) -> None:
    """Look up creator's webhook_url and API key, then deliver if configured."""
    from tradearena.db.database import CreatorORM

    creator = db_session.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator or not creator.webhook_url:
        return

    # Use the raw API key (dev) or the hash as HMAC secret.
    # In production the raw key isn't stored, so we use api_key_hash.
    secret = creator.api_key_hash or creator.api_key_dev or creator.id
    asyncio.create_task(deliver_webhook(creator.webhook_url, event, data, secret))


async def fire_webhooks_for_creators(
    db_session,
    creator_ids: set[str],
    event: str,
    data_fn,
) -> None:
    """Fire webhooks for multiple creators. data_fn(creator_id) -> dict."""
    from tradearena.db.database import CreatorORM

    creators = (
        db_session.query(CreatorORM)
        .filter(
            CreatorORM.id.in_(creator_ids),
            CreatorORM.webhook_url.isnot(None),
        )
        .all()
    )
    for creator in creators:
        secret = creator.api_key_hash or creator.api_key_dev or creator.id
        data = data_fn(creator.id)
        asyncio.create_task(deliver_webhook(creator.webhook_url, event, data, secret))
