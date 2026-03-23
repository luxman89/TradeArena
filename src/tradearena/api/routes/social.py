"""Social features: follow/unfollow creators, comment on signals, following feed."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from tradearena.api.deps import require_jwt_token
from tradearena.db.database import (
    CreatorORM,
    FollowORM,
    SignalCommentORM,
    SignalORM,
    get_db,
)
from tradearena.models.responses import (
    FollowersResponse,
    FollowingFeedResponse,
    FollowingResponse,
    FollowResponse,
    SignalCommentsResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Follow / Unfollow
# ---------------------------------------------------------------------------


@router.post(
    "/creator/{creator_id}/follow",
    status_code=201,
    response_model=FollowResponse,
    summary="Follow a creator",
    tags=["social"],
    responses={
        404: {"description": "Creator not found"},
        409: {"description": "Already following"},
        422: {"description": "Cannot follow yourself"},
    },
)
async def follow_creator(
    creator_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_jwt_token),
) -> dict:
    """Follow a creator. Requires JWT auth."""
    if current_user == creator_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot follow yourself",
        )
    target = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{creator_id}' not found",
        )
    existing = (
        db.query(FollowORM)
        .filter(FollowORM.follower_id == current_user, FollowORM.followed_id == creator_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already following this creator",
        )
    now = datetime.now(UTC)
    follow = FollowORM(follower_id=current_user, followed_id=creator_id, created_at=now)
    db.add(follow)
    db.commit()
    return {
        "follower_id": current_user,
        "followed_id": creator_id,
        "created_at": now.isoformat(),
    }


@router.delete(
    "/creator/{creator_id}/follow",
    status_code=200,
    summary="Unfollow a creator",
    tags=["social"],
    responses={
        404: {"description": "Not following this creator"},
    },
)
async def unfollow_creator(
    creator_id: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_jwt_token),
) -> dict:
    """Unfollow a creator. Requires JWT auth."""
    follow = (
        db.query(FollowORM)
        .filter(FollowORM.follower_id == current_user, FollowORM.followed_id == creator_id)
        .first()
    )
    if not follow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not following this creator",
        )
    db.delete(follow)
    db.commit()
    return {"detail": "Unfollowed successfully"}


@router.get(
    "/creator/{creator_id}/followers",
    response_model=FollowersResponse,
    summary="List followers of a creator",
    tags=["social"],
    responses={404: {"description": "Creator not found"}},
)
async def list_followers(
    creator_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Return paginated list of followers for a creator."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{creator_id}' not found",
        )
    total = db.query(FollowORM).filter(FollowORM.followed_id == creator_id).count()
    follows = (
        db.query(FollowORM)
        .filter(FollowORM.followed_id == creator_id)
        .order_by(FollowORM.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    followers = []
    for f in follows:
        follower = db.query(CreatorORM).filter(CreatorORM.id == f.follower_id).first()
        if follower:
            followers.append(
                {
                    "creator_id": follower.id,
                    "display_name": follower.display_name,
                    "followed_at": f.created_at.isoformat(),
                }
            )
    return {
        "creator_id": creator_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "followers": followers,
    }


@router.get(
    "/creator/{creator_id}/following",
    response_model=FollowingResponse,
    summary="List creators followed by a creator",
    tags=["social"],
    responses={404: {"description": "Creator not found"}},
)
async def list_following(
    creator_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Return paginated list of creators this user follows."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Creator '{creator_id}' not found",
        )
    total = db.query(FollowORM).filter(FollowORM.follower_id == creator_id).count()
    follows = (
        db.query(FollowORM)
        .filter(FollowORM.follower_id == creator_id)
        .order_by(FollowORM.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    following = []
    for f in follows:
        followed = db.query(CreatorORM).filter(CreatorORM.id == f.followed_id).first()
        if followed:
            following.append(
                {
                    "creator_id": followed.id,
                    "display_name": followed.display_name,
                    "followed_at": f.created_at.isoformat(),
                }
            )
    return {
        "creator_id": creator_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "following": following,
    }


# ---------------------------------------------------------------------------
# Following Feed
# ---------------------------------------------------------------------------


@router.get(
    "/feed/following",
    response_model=FollowingFeedResponse,
    summary="Signals from followed creators",
    tags=["social"],
)
async def following_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: str = Depends(require_jwt_token),
) -> dict:
    """Return recent signals from creators the authenticated user follows."""
    followed_ids = [
        f.followed_id
        for f in db.query(FollowORM).filter(FollowORM.follower_id == current_user).all()
    ]
    if not followed_ids:
        return {"total": 0, "offset": offset, "limit": limit, "signals": []}

    query = db.query(SignalORM).filter(SignalORM.creator_id.in_(followed_ids))
    total = query.count()
    signals = query.order_by(SignalORM.committed_at.desc()).offset(offset).limit(limit).all()

    # Batch-load display names
    creator_ids = {s.creator_id for s in signals}
    creators = {
        c.id: c.display_name
        for c in db.query(CreatorORM).filter(CreatorORM.id.in_(creator_ids)).all()
    }

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "signals": [
            {
                "signal_id": s.signal_id,
                "creator_id": s.creator_id,
                "display_name": creators.get(s.creator_id, "Unknown"),
                "asset": s.asset,
                "action": s.action,
                "confidence": s.confidence,
                "reasoning": s.reasoning,
                "committed_at": s.committed_at.isoformat(),
                "outcome": s.outcome,
            }
            for s in signals
        ],
    }


# ---------------------------------------------------------------------------
# Signal Comments
# ---------------------------------------------------------------------------

_COMMENT_MIN_LENGTH = 1
_COMMENT_MAX_LENGTH = 1000


class CommentCreateRequest(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: str) -> str:
        v = v.strip()
        if len(v) < _COMMENT_MIN_LENGTH or len(v) > _COMMENT_MAX_LENGTH:
            raise ValueError(
                f"Comment body must be {_COMMENT_MIN_LENGTH}-{_COMMENT_MAX_LENGTH} characters"
            )
        return v


@router.post(
    "/signal/{signal_id}/comments",
    status_code=201,
    response_model=dict,
    summary="Comment on a signal",
    tags=["social"],
    responses={404: {"description": "Signal not found"}},
)
async def create_comment(
    signal_id: str,
    body: CommentCreateRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_jwt_token),
) -> dict:
    """Add a comment to a signal. Requires JWT auth."""
    signal = db.query(SignalORM).filter(SignalORM.signal_id == signal_id).first()
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )
    creator = db.query(CreatorORM).filter(CreatorORM.id == current_user).first()
    now = datetime.now(UTC)
    comment_id = secrets.token_hex(16)
    comment = SignalCommentORM(
        id=comment_id,
        signal_id=signal_id,
        creator_id=current_user,
        body=body.body,
        created_at=now,
    )
    db.add(comment)
    db.commit()
    return {
        "id": comment_id,
        "signal_id": signal_id,
        "creator_id": current_user,
        "display_name": creator.display_name if creator else "Unknown",
        "body": body.body,
        "created_at": now.isoformat(),
    }


@router.get(
    "/signal/{signal_id}/comments",
    response_model=SignalCommentsResponse,
    summary="List comments on a signal",
    tags=["social"],
    responses={404: {"description": "Signal not found"}},
)
async def list_comments(
    signal_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Return paginated comments for a signal."""
    signal = db.query(SignalORM).filter(SignalORM.signal_id == signal_id).first()
    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )
    total = db.query(SignalCommentORM).filter(SignalCommentORM.signal_id == signal_id).count()
    comments = (
        db.query(SignalCommentORM)
        .filter(SignalCommentORM.signal_id == signal_id)
        .order_by(SignalCommentORM.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    # Batch-load display names
    creator_ids = {c.creator_id for c in comments}
    creators = {
        cr.id: cr.display_name
        for cr in db.query(CreatorORM).filter(CreatorORM.id.in_(creator_ids)).all()
    }
    return {
        "signal_id": signal_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "comments": [
            {
                "id": c.id,
                "signal_id": c.signal_id,
                "creator_id": c.creator_id,
                "display_name": creators.get(c.creator_id, "Unknown"),
                "body": c.body,
                "created_at": c.created_at.isoformat(),
            }
            for c in comments
        ],
    }
