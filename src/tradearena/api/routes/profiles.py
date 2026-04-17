"""Public creator profiles with shareable stats and OG image generation."""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from tradearena.core.leveling import glow_for_level, title_for_level
from tradearena.db.database import BattleORM, CreatorORM, CreatorScoreORM, SignalORM, get_db

router = APIRouter(prefix="/api/v1/users", tags=["profiles"])


def _find_creator(db: Session, username: str) -> CreatorORM:
    """Look up a creator by id or github_username."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == username).first()
    if not creator:
        creator = db.query(CreatorORM).filter(CreatorORM.github_username == username).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found",
        )
    return creator


def _github_avatar_url(creator: CreatorORM) -> str | None:
    """Return GitHub avatar URL if the creator has a linked GitHub account."""
    if creator.github_id:
        return f"https://avatars.githubusercontent.com/u/{creator.github_id}?v=4&s=200"
    return None


def _battle_record(db: Session, creator_id: str) -> dict:
    """Compute win/loss/draw record from resolved battles."""
    battles = (
        db.query(BattleORM)
        .filter(
            BattleORM.status == "RESOLVED",
            or_(
                BattleORM.creator1_id == creator_id,
                BattleORM.creator2_id == creator_id,
            ),
        )
        .all()
    )
    wins = sum(1 for b in battles if b.winner_id == creator_id)
    losses = sum(1 for b in battles if b.winner_id and b.winner_id != creator_id)
    draws = len(battles) - wins - losses
    return {"wins": wins, "losses": losses, "draws": draws, "total": len(battles)}


def _leaderboard_rank(db: Session, creator_id: str) -> int | None:
    """Return 1-indexed leaderboard rank based on composite score, or None."""
    scores = (
        db.query(CreatorScoreORM)
        .filter(CreatorScoreORM.total_signals > 0)
        .order_by(CreatorScoreORM.composite_score.desc())
        .all()
    )
    for i, s in enumerate(scores, 1):
        if s.creator_id == creator_id:
            return i
    return None


@router.get(
    "/{username}/profile",
    summary="Get public user profile",
    responses={404: {"description": "User not found"}},
)
async def get_user_profile(
    username: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return public profile for a creator, including level, title, avatar, and scores."""
    creator = _find_creator(db, username)
    score = creator.score
    xp = score.xp if score else 0
    level = score.level if score else 1

    return {
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "avatar_index": creator.avatar_index or 0,
        "github_avatar_url": _github_avatar_url(creator),
        "github_username": creator.github_username,
        "strategy_description": creator.strategy_description,
        "created_at": creator.created_at.isoformat(),
        "level": level,
        "xp": xp,
        "streak_days": creator.streak_days or 0,
        "title": title_for_level(level),
        "glow": glow_for_level(level),
        "scores": {
            "composite": round(score.composite_score, 4) if score else 0.0,
            "win_rate": round(score.win_rate, 4) if score else 0.0,
            "risk_adjusted_return": round(score.risk_adjusted_return, 4) if score else 0.0,
            "consistency": round(score.consistency, 4) if score else 0.0,
            "confidence_calibration": round(score.confidence_calibration, 4) if score else 0.0,
            "total_signals": score.total_signals if score else 0,
        },
    }


@router.get(
    "/{username}/stats",
    summary="Get user stats for sharing",
    responses={404: {"description": "User not found"}},
)
async def get_user_stats(
    username: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return aggregated stats: signal counts, win/loss record, battles, ranking."""
    creator = _find_creator(db, username)
    score = creator.score
    xp = score.xp if score else 0
    level = score.level if score else 1

    # Signal outcome counts
    total_signals = score.total_signals if score else 0
    wins = (
        db.query(SignalORM)
        .filter(SignalORM.creator_id == creator.id, SignalORM.outcome == "WIN")
        .count()
    )
    losses = (
        db.query(SignalORM)
        .filter(SignalORM.creator_id == creator.id, SignalORM.outcome == "LOSS")
        .count()
    )
    neutrals = (
        db.query(SignalORM)
        .filter(SignalORM.creator_id == creator.id, SignalORM.outcome == "NEUTRAL")
        .count()
    )
    pending = total_signals - wins - losses - neutrals

    # Active bots (creators whose id ends with b0t pattern are bots, but
    # for user stats we count how many bots a user has — currently N/A,
    # so we skip this and return 0)
    bot_count = 0

    # Battle record
    battles = _battle_record(db, creator.id)

    # Leaderboard rank
    rank = _leaderboard_rank(db, creator.id)

    return {
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "github_avatar_url": _github_avatar_url(creator),
        "level": level,
        "xp": xp,
        "title": title_for_level(level),
        "glow": glow_for_level(level),
        "joined": creator.created_at.isoformat(),
        "signals": {
            "total": total_signals,
            "wins": wins,
            "losses": losses,
            "neutrals": neutrals,
            "pending": pending,
            "win_rate": round(score.win_rate, 4) if score else 0.0,
        },
        "battles": battles,
        "ranking": {
            "composite_score": round(score.composite_score, 4) if score else 0.0,
            "leaderboard_rank": rank,
        },
        "bot_count": bot_count,
    }


# ---------------------------------------------------------------------------
# OG image generation
# ---------------------------------------------------------------------------


def _generate_og_image(
    display_name: str,
    title: str | None,
    level: int,
    composite_score: float,
    win_rate: float,
    total_signals: int,
    rank: int | None,
    division: str,
) -> bytes:
    """Generate a 1200x630 OG image card as PNG bytes."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 630
    img = Image.new("RGB", (W, H), color=(15, 15, 25))
    draw = ImageDraw.Draw(img)

    # Try to use a system font, fall back to default
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_brand = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except OSError:
        font_lg = ImageFont.load_default()
        font_md = font_lg
        font_sm = font_lg
        font_brand = font_lg

    # Background gradient effect (dark blue to darker)
    for y in range(H):
        r = int(15 + (y / H) * 10)
        g = int(15 + (y / H) * 5)
        b = int(25 + (y / H) * 20)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Accent line at top
    draw.rectangle([(0, 0), (W, 6)], fill=(0, 200, 150))

    # Brand
    draw.text((60, 40), "TradeArena", fill=(0, 200, 150), font=font_brand)

    # Division badge
    div_colors = {"crypto": (0, 200, 150), "polymarket": (150, 100, 255), "multi": (255, 180, 0)}
    div_color = div_colors.get(division, (200, 200, 200))
    draw.text((W - 200, 45), division.upper(), fill=div_color, font=font_sm)

    # Display name
    draw.text((60, 110), display_name, fill=(255, 255, 255), font=font_lg)

    # Title + Level
    subtitle = f"Level {level}"
    if title:
        subtitle = f"{title} · Level {level}"
    draw.text((60, 175), subtitle, fill=(180, 180, 200), font=font_md)

    # Separator
    draw.line([(60, 230), (W - 60, 230)], fill=(60, 60, 80), width=2)

    # Stats grid (2 rows x 3 cols)
    stats = [
        ("Composite Score", f"{composite_score:.2f}"),
        ("Win Rate", f"{win_rate * 100:.1f}%"),
        ("Signals", str(total_signals)),
        ("Rank", f"#{rank}" if rank else "—"),
    ]

    col_width = (W - 120) // 3
    for i, (label, value) in enumerate(stats):
        col = i % 3
        row = i // 3
        x = 60 + col * col_width
        y = 270 + row * 140

        draw.text((x, y), value, fill=(255, 255, 255), font=font_lg)
        draw.text((x, y + 60), label, fill=(120, 120, 150), font=font_sm)

    # Footer
    draw.line([(60, H - 70), (W - 60, H - 70)], fill=(60, 60, 80), width=1)
    draw.text((60, H - 55), "tradearena.duckdns.org", fill=(100, 100, 130), font=font_sm)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get(
    "/{username}/og-image.png",
    summary="Generate OG share image",
    responses={
        200: {"content": {"image/png": {}}, "description": "OG image card"},
        404: {"description": "User not found"},
    },
)
async def get_og_image(
    username: str,
    db: Session = Depends(get_db),
) -> Response:
    """Generate a 1200x630 PNG stats card for social media sharing."""
    creator = _find_creator(db, username)
    score = creator.score
    level = score.level if score else 1
    rank = _leaderboard_rank(db, creator.id)

    png_bytes = _generate_og_image(
        display_name=creator.display_name,
        title=title_for_level(level),
        level=level,
        composite_score=score.composite_score if score else 0.0,
        win_rate=score.win_rate if score else 0.0,
        total_signals=score.total_signals if score else 0,
        rank=rank,
        division=creator.division,
    )

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )
