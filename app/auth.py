"""School OIDC login and short-lived, revocable browser sessions."""

import hashlib
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.models import User
from app.redis_client import redis_client


OIDC_METADATA_URL = os.environ.get("OIDC_METADATA_URL", "")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
AUTH_SESSION_SECRET = os.environ.get("AUTH_SESSION_SECRET", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:1234").rstrip("/")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SESSION_TTL_SECONDS = 8 * 60 * 60
COOKIE_NAME = "headcount_session"

OIDC_CONFIGURED = all((OIDC_METADATA_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, AUTH_SESSION_SECRET))

def validate_production_config() -> None:
    if not OIDC_CONFIGURED or any(
        value.startswith("REPLACE_WITH_")
        for value in (OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, AUTH_SESSION_SECRET)
    ):
        raise RuntimeError("Production requires configured school OIDC credentials")
    if urlparse(OIDC_METADATA_URL).scheme != "https":
        raise RuntimeError("Production requires an HTTPS OIDC metadata URL")
    public_url = urlparse(PUBLIC_BASE_URL)
    if public_url.scheme != "https" or not public_url.hostname or public_url.path not in ("", "/") or not COOKIE_SECURE:
        raise RuntimeError("Production requires an HTTPS public origin and secure cookies")
    declared_domain = os.environ.get("HEADCOUNT_DOMAIN")
    if declared_domain and public_url.hostname != declared_domain:
        raise RuntimeError("PUBLIC_BASE_URL must use HEADCOUNT_DOMAIN")
    if len(AUTH_SESSION_SECRET) < 32:
        raise RuntimeError("Production requires an AUTH_SESSION_SECRET of at least 32 characters")

oauth = OAuth()
if OIDC_CONFIGURED:
    oauth.register(
        name="school",
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata_url=OIDC_METADATA_URL,
        client_kwargs={"scope": "openid profile email"},
    )


@dataclass(frozen=True)
class AuthContext:
    user: User
    csrf: str


def _session_key(raw_token: str) -> str:
    return "browser-session:" + hashlib.sha256(raw_token.encode()).hexdigest()


async def create_browser_session(response, user: User) -> str:
    raw_token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    await run_in_threadpool(
        redis_client.setex,
        _session_key(raw_token),
        SESSION_TTL_SECONDS,
        json.dumps({"user_id": str(user.user_id), "csrf": csrf}),
    )
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return csrf


async def delete_browser_session(request: Request, response) -> None:
    raw_token = request.cookies.get(COOKIE_NAME)
    if raw_token:
        await run_in_threadpool(redis_client.delete, _session_key(raw_token))
    response.delete_cookie(COOKIE_NAME, path="/")


async def optional_auth(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> AuthContext | None:
    raw_token = request.cookies.get(COOKIE_NAME)
    if not raw_token:
        return None
    stored = await run_in_threadpool(redis_client.get, _session_key(raw_token))
    if not stored:
        return None
    try:
        data = json.loads(stored)
        user = await db.get(User, uuid.UUID(data["user_id"]))
        csrf = data["csrf"]
    except (KeyError, TypeError, ValueError):
        return None
    if user is None:
        return None
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, csrf):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return AuthContext(user=user, csrf=csrf)


async def require_auth(context: AuthContext | None = Depends(optional_auth)) -> AuthContext:
    if context is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return context


async def require_instructor(context: AuthContext = Depends(require_auth)) -> AuthContext:
    if context.user.role != "instructor":
        raise HTTPException(status_code=403, detail="Instructor access required")
    return context
