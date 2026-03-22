"""Webhook management endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from tradearena.api.deps import require_api_key
from tradearena.db.database import CreatorORM, get_db

router = APIRouter(tags=["webhooks"])

_URL_RE = re.compile(r"^https?://\S+$")


class WebhookSetRequest(BaseModel):
    url: str | None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                return None
            if not _URL_RE.match(v):
                raise ValueError("webhook URL must be a valid http:// or https:// URL")
            if len(v) > 512:
                raise ValueError("webhook URL must be 512 characters or fewer")
        return v


@router.post(
    "/creator/webhook",
    summary="Register or update webhook URL",
    responses={
        404: {"description": "Creator not found"},
    },
)
async def set_webhook(
    payload: WebhookSetRequest,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    """Set or clear the webhook URL for the authenticated creator.

    Pass `{"url": null}` to unregister the webhook.
    """
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator not found",
        )

    creator.webhook_url = payload.url
    db.commit()

    return {
        "creator_id": creator_id,
        "webhook_url": creator.webhook_url,
        "message": "Webhook URL updated" if payload.url else "Webhook URL cleared",
    }


@router.post(
    "/creator/webhook/test",
    summary="Send a test webhook event",
    responses={
        400: {"description": "No webhook URL configured"},
        404: {"description": "Creator not found"},
    },
)
async def test_webhook(
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    """Send a test event to the creator's registered webhook URL."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator not found",
        )
    if not creator.webhook_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No webhook URL configured. Set one with POST /creator/webhook first.",
        )

    secret = creator.api_key_hash or creator.api_key_dev or creator.id
    test_data = {
        "creator_id": creator_id,
        "message": "This is a test webhook from TradeArena.",
    }

    # Deliver directly (no retry for test) — use await so we can report result
    import json
    import time

    import httpx

    from tradearena.core.webhooks import _compute_signature

    payload = {
        "event": "webhook.test",
        "data": test_data,
        "timestamp": time.time(),
    }
    body = json.dumps(payload, default=str, sort_keys=True)
    body_bytes = body.encode()
    signature = _compute_signature(body_bytes, secret)

    headers = {
        "Content-Type": "application/json",
        "X-TradeArena-Signature": f"sha256={signature}",
        "X-TradeArena-Event": "webhook.test",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(creator.webhook_url, content=body_bytes, headers=headers)
        success = 200 <= resp.status_code < 300
        return {
            "success": success,
            "status_code": resp.status_code,
            "webhook_url": creator.webhook_url,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "webhook_url": creator.webhook_url,
        }
