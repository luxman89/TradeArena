"""Auth endpoints: register with password, login, profile, avatar change, GitHub OAuth."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

import bcrypt as _bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from tradearena.api.deps import create_jwt, require_jwt_token
from tradearena.core.email import generate_unsubscribe_token
from tradearena.core.leveling import (
    glow_for_level,
    title_for_level,
    unlocked_avatars,
    xp_for_current_level,
    xp_to_next_level,
)
from tradearena.db.database import CreatorORM, get_db
from tradearena.models.responses import (
    AuthLoginResponse,
    AuthMeResponse,
    AuthRegisterResponse,
    AvatarUpdateResponse,
    GitHubCallbackResponse,
    ProfileUpdateResponse,
)

_logger = logging.getLogger(__name__)

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.getenv(
    "GITHUB_REDIRECT_URI",
    os.getenv("BASE_URL", "https://tradearena.app") + "/auth/github/callback",
)

router = APIRouter(prefix="/auth", tags=["auth"])

_VALID_DIVISIONS = {"crypto", "polymarket", "multi"}
_STARTER_AVATARS = {0, 1, 2, 3}


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str
    division: str
    strategy_description: str
    avatar_index: int = 0

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        if not (3 <= len(v) <= 50):
            raise ValueError("display_name must be 3-50 characters")
        return v

    @field_validator("division")
    @classmethod
    def validate_division(cls, v: str) -> str:
        if v not in _VALID_DIVISIONS:
            raise ValueError(f"division must be one of: {', '.join(sorted(_VALID_DIVISIONS))}")
        return v

    @field_validator("strategy_description")
    @classmethod
    def validate_strategy_description(cls, v: str) -> str:
        if not (20 <= len(v) <= 500):
            raise ValueError("strategy_description must be 20-500 characters")
        return v

    @field_validator("avatar_index")
    @classmethod
    def validate_avatar_index(cls, v: int) -> int:
        if v not in _STARTER_AVATARS:
            raise ValueError(
                f"avatar_index must be one of {sorted(_STARTER_AVATARS)} at registration"
            )
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = None
    strategy_description: str | None = None
    division: str | None = None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        if v is not None and not (3 <= len(v) <= 50):
            raise ValueError("display_name must be 3-50 characters")
        return v

    @field_validator("strategy_description")
    @classmethod
    def validate_strategy_description(cls, v: str | None) -> str | None:
        if v is not None and not (20 <= len(v) <= 500):
            raise ValueError("strategy_description must be 20-500 characters")
        return v

    @field_validator("division")
    @classmethod
    def validate_division(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_DIVISIONS:
            raise ValueError(f"division must be one of: {', '.join(sorted(_VALID_DIVISIONS))}")
        return v


class AvatarUpdateRequest(BaseModel):
    avatar_index: int

    @field_validator("avatar_index")
    @classmethod
    def validate_range(cls, v: int) -> int:
        if not (0 <= v <= 9):
            raise ValueError("avatar_index must be 0-9")
        return v


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    status_code=201,
    response_model=AuthRegisterResponse,
    summary="Register with email and password",
    responses={
        409: {"description": "Email already registered"},
    },
)
async def register(body: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """Register a new creator with email + password. Returns JWT + API key."""
    if db.query(CreatorORM).filter(CreatorORM.email == body.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    slug = _slugify(body.display_name)
    creator_id = f"{slug}-{secrets.token_hex(2)}"
    if db.query(CreatorORM).filter(CreatorORM.id == creator_id).first():
        creator_id = f"{slug}-{secrets.token_hex(2)}"

    api_key = f"ta-{secrets.token_hex(16)}"
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    now = datetime.now(UTC)
    unsub_token = generate_unsubscribe_token()
    creator = CreatorORM(
        id=creator_id,
        display_name=body.display_name,
        division=body.division,
        email=body.email,
        strategy_description=body.strategy_description,
        api_key_hash=api_key_hash,
        password_hash=_bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode(),
        avatar_index=body.avatar_index,
        unsubscribe_token=unsub_token,
        created_at=now,
    )
    db.add(creator)
    db.commit()

    token = create_jwt(creator_id)

    return {
        "creator_id": creator_id,
        "api_key": api_key,
        "token": token,
        "display_name": body.display_name,
        "division": body.division,
        "avatar_index": body.avatar_index,
        "level": 1,
        "xp": 0,
        "created_at": now.isoformat(),
    }


@router.post(
    "/login",
    response_model=AuthLoginResponse,
    summary="Login with email and password",
    responses={
        401: {"description": "Invalid email or password"},
    },
)
async def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """Login with email + password. Returns JWT + profile."""
    creator = db.query(CreatorORM).filter(CreatorORM.email == body.email).first()
    if not creator or not creator.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not _bcrypt.checkpw(body.password.encode(), creator.password_hash.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    score = creator.score
    xp = score.xp if score else 0
    level = score.level if score else 1

    token = create_jwt(creator.id)

    return {
        "token": token,
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "avatar_index": creator.avatar_index or 0,
        "level": level,
        "xp": xp,
        "title": title_for_level(level),
    }


@router.get(
    "/me",
    response_model=AuthMeResponse,
    summary="Get current user profile",
    responses={
        404: {"description": "Creator not found"},
    },
)
async def get_me(
    creator_id: str = Depends(require_jwt_token),
    db: Session = Depends(get_db),
) -> dict:
    """Return current user profile with level, XP, unlocked avatars."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    score = creator.score
    xp = score.xp if score else 0
    level = score.level if score else 1
    progress, needed = xp_for_current_level(xp)

    return {
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "avatar_index": creator.avatar_index or 0,
        "level": level,
        "xp": xp,
        "xp_progress": progress,
        "xp_needed": needed,
        "xp_to_next": xp_to_next_level(xp),
        "title": title_for_level(level),
        "glow": glow_for_level(level),
        "unlocked_avatars": unlocked_avatars(level),
        "scores": {
            "composite": round(score.composite_score, 4) if score else 0.0,
            "win_rate": round(score.win_rate, 4) if score else 0.0,
            "total_signals": score.total_signals if score else 0,
        },
    }


@router.patch(
    "/profile",
    response_model=ProfileUpdateResponse,
    summary="Update user profile",
    responses={
        404: {"description": "Creator not found"},
    },
)
async def update_profile(
    body: ProfileUpdateRequest,
    creator_id: str = Depends(require_jwt_token),
    db: Session = Depends(get_db),
) -> dict:
    """Update profile fields: display_name, strategy_description, division."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    if body.display_name is not None:
        creator.display_name = body.display_name
    if body.strategy_description is not None:
        creator.strategy_description = body.strategy_description
    if body.division is not None:
        creator.division = body.division
    db.commit()

    return {
        "creator_id": creator.id,
        "display_name": creator.display_name,
        "division": creator.division,
        "strategy_description": creator.strategy_description,
        "message": "Profile updated",
    }


@router.put(
    "/avatar",
    response_model=AvatarUpdateResponse,
    summary="Change avatar",
    responses={
        403: {"description": "Avatar locked — requires higher level"},
        404: {"description": "Creator not found"},
    },
)
async def update_avatar(
    body: AvatarUpdateRequest,
    creator_id: str = Depends(require_jwt_token),
    db: Session = Depends(get_db),
) -> dict:
    """Change avatar. Validates against unlocked avatars for user's level."""
    creator = db.query(CreatorORM).filter(CreatorORM.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    score = creator.score
    level = score.level if score else 1
    available = unlocked_avatars(level)

    if body.avatar_index not in available:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Avatar {body.avatar_index} requires a higher level. Available: {available}",
        )

    creator.avatar_index = body.avatar_index
    db.commit()

    return {"avatar_index": body.avatar_index, "message": "Avatar updated"}


# ---------------------------------------------------------------------------
# GitHub OAuth
# ---------------------------------------------------------------------------

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def _require_github_config() -> None:
    """Raise 503 if GitHub OAuth is not configured."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured on this server",
        )


class GitHubCallbackRequest(BaseModel):
    code: str
    division: str = "crypto"

    @field_validator("division")
    @classmethod
    def validate_division(cls, v: str) -> str:
        if v not in _VALID_DIVISIONS:
            raise ValueError(f"division must be one of: {', '.join(sorted(_VALID_DIVISIONS))}")
        return v


@router.get(
    "/github",
    summary="Initiate GitHub OAuth flow",
    responses={
        503: {"description": "GitHub OAuth not configured"},
    },
)
async def github_redirect() -> dict:
    """Return the GitHub authorization URL for the frontend to redirect to."""
    _require_github_config()
    params = urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": GITHUB_REDIRECT_URI,
            "scope": "read:user user:email",
        }
    )
    return {"authorization_url": f"{_GITHUB_AUTHORIZE_URL}?{params}"}


@router.post(
    "/github/callback",
    response_model=GitHubCallbackResponse,
    summary="Complete GitHub OAuth signup/login",
    responses={
        400: {"description": "GitHub authentication failed"},
        503: {"description": "GitHub OAuth not configured"},
    },
)
async def github_callback(
    body: GitHubCallbackRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Exchange GitHub OAuth code for access token, then login or create account.

    Flow:
    1. Exchange code for GitHub access token.
    2. Fetch GitHub user profile + primary email.
    3. If github_id matches existing creator → login.
    4. If email matches existing creator → link GitHub account + login.
    5. Otherwise → create new creator with auto-generated API key.
    """
    _require_github_config()

    # Step 1: Exchange code for access token
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            _GITHUB_TOKEN_URL,
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": body.code,
                "redirect_uri": GITHUB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )

    if token_resp.status_code != 200:
        _logger.warning("GitHub token exchange failed: %s", token_resp.status_code)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange GitHub authorization code",
        )

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        error_desc = token_data.get("error_description", "Unknown error")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {error_desc}",
        )

    # Step 2: Fetch GitHub user profile + email
    gh_headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        user_resp = await client.get(_GITHUB_USER_URL, headers=gh_headers)
        if user_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch GitHub user profile",
            )
        gh_user = user_resp.json()

        # Fetch primary verified email if not public
        gh_email = gh_user.get("email")
        if not gh_email:
            emails_resp = await client.get(_GITHUB_EMAILS_URL, headers=gh_headers)
            if emails_resp.status_code == 200:
                for entry in emails_resp.json():
                    if entry.get("primary") and entry.get("verified"):
                        gh_email = entry["email"]
                        break

    gh_id = str(gh_user["id"])
    gh_username = gh_user.get("login", "")
    gh_display_name = gh_user.get("name") or gh_username

    # Step 3: Check if github_id already linked
    creator = db.query(CreatorORM).filter(CreatorORM.github_id == gh_id).first()
    if creator:
        # Existing GitHub-linked account — login
        score = creator.score
        xp = score.xp if score else 0
        level = score.level if score else 1
        # Update github_username in case it changed
        if creator.github_username != gh_username:
            creator.github_username = gh_username
            db.commit()
        return {
            "token": create_jwt(creator.id),
            "creator_id": creator.id,
            "api_key": None,
            "display_name": creator.display_name,
            "division": creator.division,
            "avatar_index": creator.avatar_index or 0,
            "level": level,
            "xp": xp,
            "title": title_for_level(level),
            "is_new_account": False,
        }

    # Step 4: Check if email matches existing account → link
    if gh_email:
        creator = db.query(CreatorORM).filter(CreatorORM.email == gh_email.lower()).first()
        if creator:
            creator.github_id = gh_id
            creator.github_username = gh_username
            db.commit()

            score = creator.score
            xp = score.xp if score else 0
            level = score.level if score else 1
            return {
                "token": create_jwt(creator.id),
                "creator_id": creator.id,
                "api_key": None,
                "display_name": creator.display_name,
                "division": creator.division,
                "avatar_index": creator.avatar_index or 0,
                "level": level,
                "xp": xp,
                "title": title_for_level(level),
                "is_new_account": False,
            }

    # Step 5: New account — create creator with auto-generated API key
    # Sanitize display name (GitHub names can be anything)
    display_name = gh_display_name[:50] if len(gh_display_name) >= 3 else gh_username[:50]
    if len(display_name) < 3:
        display_name = f"trader-{secrets.token_hex(2)}"

    slug = _slugify(display_name)
    if not slug:
        slug = f"trader-{secrets.token_hex(2)}"
    creator_id = f"{slug}-{secrets.token_hex(2)}"
    if db.query(CreatorORM).filter(CreatorORM.id == creator_id).first():
        creator_id = f"{slug}-{secrets.token_hex(2)}"

    api_key = f"ta-{secrets.token_hex(16)}"
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    now = datetime.now(UTC)

    creator = CreatorORM(
        id=creator_id,
        display_name=display_name,
        division=body.division,
        email=gh_email.lower() if gh_email else None,
        api_key_hash=api_key_hash,
        github_id=gh_id,
        github_username=gh_username,
        avatar_index=0,
        created_at=now,
    )
    db.add(creator)
    db.commit()

    return {
        "token": create_jwt(creator_id),
        "creator_id": creator_id,
        "api_key": api_key,
        "display_name": display_name,
        "division": body.division,
        "avatar_index": 0,
        "level": 1,
        "xp": 0,
        "title": None,
        "is_new_account": True,
    }
