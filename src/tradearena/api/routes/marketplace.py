"""Bot marketplace — discover, publish, and fork bot templates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from tradearena.api.deps import require_api_key
from tradearena.db.database import BotTemplateORM, get_db

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

VALID_STRATEGY_TYPES = {"momentum", "mean_reversion", "sentiment", "volatility", "custom"}
MAX_TEMPLATES_PER_CREATOR = 50


def _template_to_dict(t: BotTemplateORM, include_code: bool = False) -> dict:
    """Serialize a BotTemplateORM to a response dict."""
    d = {
        "id": t.id,
        "creator_id": t.creator_id,
        "name": t.name,
        "description": t.description,
        "strategy_type": t.strategy_type,
        "config": t.config,
        "version": t.version,
        "tags": t.tags or [],
        "is_public": t.is_public,
        "fork_count": t.fork_count,
        "forked_from_id": t.forked_from_id,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }
    if include_code:
        d["code"] = t.code
    return d


@router.get(
    "/templates",
    summary="Browse bot templates",
    description="List public bot templates with optional filtering.",
)
async def list_templates(
    strategy_type: str | None = Query(None, description="Filter by strategy type"),
    tag: str | None = Query(None, description="Filter by tag"),
    creator_id: str | None = Query(None, description="Filter by creator"),
    q: str | None = Query(None, description="Search name/description"),
    sort: str = Query("popular", description="Sort: popular, recent, name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(BotTemplateORM).filter(BotTemplateORM.is_public.is_(True))

    if strategy_type:
        if strategy_type not in VALID_STRATEGY_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid strategy_type. Must be one of: {sorted(VALID_STRATEGY_TYPES)}",
            )
        query = query.filter(BotTemplateORM.strategy_type == strategy_type)

    if creator_id:
        query = query.filter(BotTemplateORM.creator_id == creator_id)

    if q:
        search = f"%{q}%"
        query = query.filter(
            BotTemplateORM.name.ilike(search) | BotTemplateORM.description.ilike(search)
        )

    if tag:
        # JSON array contains — works for SQLite and Postgres
        query = query.filter(BotTemplateORM.tags.like(f'%"{tag}"%'))

    if sort == "recent":
        query = query.order_by(BotTemplateORM.created_at.desc())
    elif sort == "name":
        query = query.order_by(BotTemplateORM.name.asc())
    else:  # popular (default)
        query = query.order_by(BotTemplateORM.fork_count.desc(), BotTemplateORM.created_at.desc())

    total = query.count()
    templates = query.offset(offset).limit(limit).all()

    return {
        "templates": [_template_to_dict(t) for t in templates],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/templates/{template_id}",
    summary="Get bot template details",
)
async def get_template(
    template_id: str,
    db: Session = Depends(get_db),
) -> dict:
    t = db.query(BotTemplateORM).filter(BotTemplateORM.id == template_id).first()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if not t.is_public:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return _template_to_dict(t, include_code=True)


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    summary="Publish a bot template",
)
async def publish_template(
    payload: dict,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    name = (payload.get("name") or "").strip()
    if not name or len(name) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name is required and must be <= 128 chars",
        )

    description = (payload.get("description") or "").strip()
    if not description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="description is required",
        )

    code = (payload.get("code") or "").strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code is required",
        )

    strategy_type = payload.get("strategy_type", "custom")
    if strategy_type not in VALID_STRATEGY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid strategy_type. Must be one of: {sorted(VALID_STRATEGY_TYPES)}",
        )

    tags = payload.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tags must be a list of strings",
        )
    if len(tags) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 tags allowed",
        )

    # Check per-creator limit
    count = db.query(BotTemplateORM).filter(BotTemplateORM.creator_id == creator_id).count()
    if count >= MAX_TEMPLATES_PER_CREATOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_TEMPLATES_PER_CREATOR} templates per creator",
        )

    now = datetime.now(UTC)
    template = BotTemplateORM(
        id=uuid.uuid4().hex,
        creator_id=creator_id,
        name=name,
        description=description,
        strategy_type=strategy_type,
        code=code,
        config=payload.get("config"),
        version=1,
        tags=tags,
        is_public=payload.get("is_public", True),
        fork_count=0,
        forked_from_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return _template_to_dict(template, include_code=True)


@router.patch(
    "/templates/{template_id}",
    summary="Update a bot template (owner only)",
)
async def update_template(
    template_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    t = db.query(BotTemplateORM).filter(BotTemplateORM.id == template_id).first()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if t.creator_id != creator_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the template owner")

    updated = False
    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name or len(name) > 128:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name must be non-empty and <= 128 chars",
            )
        t.name = name
        updated = True

    if "description" in payload:
        t.description = (payload["description"] or "").strip()
        updated = True

    if "code" in payload:
        code = (payload["code"] or "").strip()
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="code cannot be empty",
            )
        t.code = code
        t.version += 1  # bump version on code change
        updated = True

    if "strategy_type" in payload:
        if payload["strategy_type"] not in VALID_STRATEGY_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid strategy_type. Must be one of: {sorted(VALID_STRATEGY_TYPES)}",
            )
        t.strategy_type = payload["strategy_type"]
        updated = True

    if "config" in payload:
        t.config = payload["config"]
        updated = True

    if "tags" in payload:
        tags = payload["tags"]
        if not isinstance(tags, list) or not all(isinstance(tg, str) for tg in tags):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tags must be a list of strings",
            )
        if len(tags) > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 10 tags allowed",
            )
        t.tags = tags
        updated = True

    if "is_public" in payload:
        t.is_public = bool(payload["is_public"])
        updated = True

    if updated:
        t.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(t)

    return _template_to_dict(t, include_code=True)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a bot template (owner only)",
)
async def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> None:
    t = db.query(BotTemplateORM).filter(BotTemplateORM.id == template_id).first()
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if t.creator_id != creator_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the template owner")

    # Nullify forked_from_id on any forks so they aren't orphaned
    db.query(BotTemplateORM).filter(BotTemplateORM.forked_from_id == template_id).update(
        {"forked_from_id": None}
    )
    db.delete(t)
    db.commit()


@router.post(
    "/templates/{template_id}/fork",
    status_code=status.HTTP_201_CREATED,
    summary="Fork a bot template",
)
async def fork_template(
    template_id: str,
    payload: dict | None = None,
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    source = db.query(BotTemplateORM).filter(BotTemplateORM.id == template_id).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if not source.is_public and source.creator_id != creator_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    # Check per-creator limit
    count = db.query(BotTemplateORM).filter(BotTemplateORM.creator_id == creator_id).count()
    if count >= MAX_TEMPLATES_PER_CREATOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_TEMPLATES_PER_CREATOR} templates per creator",
        )

    payload = payload or {}
    fork_name = (payload.get("name") or "").strip() or f"{source.name} (fork)"
    if len(fork_name) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name must be <= 128 chars",
        )

    now = datetime.now(UTC)
    fork = BotTemplateORM(
        id=uuid.uuid4().hex,
        creator_id=creator_id,
        name=fork_name,
        description=source.description,
        strategy_type=source.strategy_type,
        code=source.code,
        config=source.config,
        version=1,
        tags=list(source.tags) if source.tags else [],
        is_public=payload.get("is_public", True),
        fork_count=0,
        forked_from_id=source.id,
        created_at=now,
        updated_at=now,
    )
    db.add(fork)

    # Increment fork count on source
    source.fork_count = (source.fork_count or 0) + 1
    source.updated_at = now

    db.commit()
    db.refresh(fork)

    return _template_to_dict(fork, include_code=True)


@router.get(
    "/my-templates",
    summary="List your own templates (public and private)",
)
async def my_templates(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    creator_id: str = Depends(require_api_key),
) -> dict:
    query = db.query(BotTemplateORM).filter(BotTemplateORM.creator_id == creator_id)
    total = query.count()
    templates = query.order_by(BotTemplateORM.updated_at.desc()).offset(offset).limit(limit).all()
    return {
        "templates": [_template_to_dict(t, include_code=True) for t in templates],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
