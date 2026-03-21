"""Email endpoints: unsubscribe, open tracking, click tracking."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from tradearena.db.database import CreatorORM, EmailEventORM, get_db

router = APIRouter(prefix="/email", tags=["email"])

# 1x1 transparent GIF for open tracking
_TRACKING_PIXEL = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00"
    b"\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
    b"\x44\x01\x00\x3b"
)


@router.get(
    "/unsubscribe",
    response_class=HTMLResponse,
    summary="Unsubscribe from onboarding emails",
    include_in_schema=False,
)
async def unsubscribe(
    token: str = Query(..., min_length=64, max_length=64),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """CAN-SPAM compliant one-click unsubscribe."""
    creator = db.query(CreatorORM).filter(CreatorORM.unsubscribe_token == token).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid unsubscribe token",
        )

    creator.email_opted_out = True
    db.commit()

    return HTMLResponse(
        content="""<!DOCTYPE html>
<html><head><title>Unsubscribed</title>
<style>body{font-family:sans-serif;background:#0a0a0a;color:#e0e0e0;
display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}
.box{text-align:center;max-width:400px;}
h1{color:#00ff88;}a{color:#00ff88;}</style></head>
<body><div class="box">
<h1>Unsubscribed</h1>
<p>You won't receive any more onboarding emails from TradeArena.</p>
<p><a href="/">Back to TradeArena</a></p>
</div></body></html>""",
        status_code=200,
    )


@router.post(
    "/unsubscribe",
    summary="One-click unsubscribe (List-Unsubscribe-Post)",
    include_in_schema=False,
)
async def unsubscribe_post(
    token: str = Query(..., min_length=64, max_length=64),
    db: Session = Depends(get_db),
) -> dict:
    """RFC 8058 one-click unsubscribe via POST."""
    creator = db.query(CreatorORM).filter(CreatorORM.unsubscribe_token == token).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid unsubscribe token",
        )

    creator.email_opted_out = True
    db.commit()
    return {"status": "unsubscribed"}


@router.get(
    "/open/{event_id}",
    summary="Track email open",
    include_in_schema=False,
)
async def track_open(event_id: str, db: Session = Depends(get_db)) -> Response:
    """Record email open via tracking pixel."""
    ev = db.query(EmailEventORM).filter(EmailEventORM.id == event_id).first()
    if ev and not ev.opened_at:
        ev.opened_at = datetime.now(UTC)
        db.commit()

    return Response(content=_TRACKING_PIXEL, media_type="image/gif")


@router.get(
    "/click/{event_id}",
    summary="Track email click",
    include_in_schema=False,
)
async def track_click(
    event_id: str,
    url: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Record email click and redirect to destination."""
    ev = db.query(EmailEventORM).filter(EmailEventORM.id == event_id).first()
    if ev and not ev.clicked_at:
        ev.clicked_at = datetime.now(UTC)
        db.commit()

    return RedirectResponse(url=url, status_code=302)
