import os, qrcode, base64, io, asyncio, secrets, time, logging
import uuid
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware

from app.scans import validate_scan
from app.db import init_db, get_session
from app import metrics, auth, records
from app.access import owned_course, owned_session

import app.tokens as token_store

load_dotenv()

from contextlib import asynccontextmanager
from app.models import Course, Session as SessionModel, User, AuditLog
from app.models import utcnow # cause I'm lazy and don't want to redefine it

INSTANCE_ID = os.environ.get("HOSTNAME", "local")
SESSION_TIME = 30
logger = logging.getLogger(__name__)

class ScanRequest(BaseModel):
    token: str
    session: str

async def rotate_tokens():
    while True:
        try:
            now = time.time()
            due_sessions = token_store.get_due_sessions(now)
            reload_times = token_store.get_reload_times(sid for sid, _ in due_sessions)
            for session_id, due_at in due_sessions:
                try:
                    reload_time = reload_times[session_id]
                    won = token_store.try_acquire_session_lock(session_id, INSTANCE_ID, reload_time)
                    metrics.ROTATION_LOCK_ATTEMPTS.labels("won" if won else "lost").inc()
                    if won:
                        token_store.set_current_token(session_id, secrets.token_urlsafe(16), reload_time)
                        token_store.set_next_due(session_id, now + reload_time)
                        metrics.TOKEN_ROTATIONS.inc()
                        metrics.ROTATION_LAG.observe(max(0, time.time() - due_at))
                except Exception:
                    metrics.ROTATOR_ERRORS.labels("rotate").inc()
                    logger.exception("Failed to rotate token for session %s", session_id)
        except Exception:
            metrics.ROTATOR_ERRORS.labels("schedule").inc()
            logger.exception("Failed to read the rotation schedule")
        finally:
            metrics.ROTATOR_ITERATIONS.inc()
            metrics.ROTATOR_LAST_ITERATION.set(time.time())
        await asyncio.sleep(token_store.TICK_INTERVAL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db() # With migrate now in compose.yml, this (should) do nothing important. But it's an extra check for safety
    task = asyncio.create_task(rotate_tokens())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)
app.include_router(records.router)
app.add_middleware(
    SessionMiddleware,
    secret_key=auth.AUTH_SESSION_SECRET or "local-dev-only-oidc-state",
    session_cookie="headcount_oidc_state",
    same_site="lax",
    https_only=auth.COOKIE_SECURE,
)

@app.middleware("http")
async def observe_http(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    started = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_name = getattr(route, "path", "unmatched")
        metrics.HTTP_REQUESTS.labels(request.method, route_name, str(status)).inc()
        metrics.HTTP_DURATION.labels(request.method, route_name).observe(time.monotonic() - started)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.post("/scan")
async def scan(payload: ScanRequest, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_auth)):
    try:
        valid, message, result = await validate_scan(payload.token, str(context.user.user_id), payload.session, db)
        try:
            session_uuid = uuid.UUID(payload.session)
            session_exists = await db.get(SessionModel, session_uuid)
        except ValueError:
            session_uuid, session_exists = None, None
        db.add(AuditLog(
            session_id=session_uuid if session_exists else None,
            user_id=context.user.user_id,
            actor_user_id=context.user.user_id,
            event_type=result,
            reason=message,
            instance_id=INSTANCE_ID,
        ))
        await db.commit()
    except Exception:
        await db.rollback()
        metrics.SCANS.labels("error").inc()
        raise
    metrics.SCANS.labels(result).inc()
    return {"valid": valid, "message": message, "result": result}

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    try:
        count = await run_in_threadpool(token_store.count_active_sessions)
    except RedisError:
        metrics.ACTIVE_SESSIONS.set(float("nan"))
        metrics.METRICS_REDIS_QUERY_SUCCESS.set(0)
    else:
        metrics.ACTIVE_SESSIONS.set(count)
        metrics.METRICS_REDIS_QUERY_SUCCESS.set(1)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/current")
async def current(session_id: str, response: Response, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    response.headers["Cache-Control"] = "no-store"
    await owned_session(db, session_id, context.user)
    if not await run_in_threadpool(token_store.is_session_active, session_id):
        return {"active": False}
    token = await run_in_threadpool(token_store.get_current_token, session_id)
    if token is None:
        return {"active": False}
    checkin_url = f"{auth.PUBLIC_BASE_URL}/check-in#{urlencode({'session': session_id, 'token': token})}"
    return {"active": True, "token": token, "qr": make_qr_data_url(checkin_url)}

@app.get("/healthz")
def healthz():
    return {"status": "ok",
            "instance": INSTANCE_ID}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, context: auth.AuthContext | None = Depends(auth.optional_auth)):
    if context is None:
        return RedirectResponse("/login", status_code=303)
    if context.user.role != "instructor":
        return RedirectResponse("/account", status_code=303)
    return templates.TemplateResponse(request, "admin.html", {"instance": INSTANCE_ID})

@app.get("/records", response_class=HTMLResponse)
def records_page(request: Request, context: auth.AuthContext | None = Depends(auth.optional_auth)):
    if context is None:
        return RedirectResponse("/login", status_code=303)
    if context.user.role != "instructor":
        raise HTTPException(status_code=403, detail="Instructor access required")
    return templates.TemplateResponse(request, "records.html", {})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, context: auth.AuthContext | None = Depends(auth.optional_auth)):
    if context is not None:
        return RedirectResponse("/" if context.user.role == "instructor" else "/check-in", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"configured": auth.OIDC_CONFIGURED})

@app.get("/account", response_class=HTMLResponse)
def student_account(request: Request, context: auth.AuthContext = Depends(auth.require_auth)):
    return RedirectResponse("/check-in", status_code=303)

@app.get("/check-in", response_class=HTMLResponse)
def checkin_page(request: Request, context: auth.AuthContext | None = Depends(auth.optional_auth)):
    if context is None:
        return RedirectResponse("/login", status_code=303)
    page = templates.TemplateResponse(request, "checkin.html", {"user": context.user})
    page.headers["Cache-Control"] = "no-store"
    page.headers["Referrer-Policy"] = "no-referrer"
    return page

@app.get("/auth/login")
async def oidc_login(request: Request):
    if not auth.OIDC_CONFIGURED:
        raise HTTPException(status_code=503, detail="School SSO is not configured")
    return await auth.oauth.school.authorize_redirect(request, f"{auth.PUBLIC_BASE_URL}/auth/callback")

@app.get("/auth/callback")
async def oidc_callback(request: Request, db: AsyncSession = Depends(get_session)):
    if not auth.OIDC_CONFIGURED:
        raise HTTPException(status_code=503, detail="School SSO is not configured")
    try:
        token = await auth.oauth.school.authorize_access_token(request)
        claims = token["userinfo"]
        issuer, subject, email = claims["iss"], claims["sub"], claims["email"]
    except Exception:
        logger.exception("School SSO callback failed")
        raise HTTPException(status_code=401, detail="School sign-in failed")
    if not all(isinstance(value, str) and value for value in (issuer, subject, email)):
        raise HTTPException(status_code=401, detail="School identity is incomplete")
    if claims.get("email_verified") is False:
        raise HTTPException(status_code=403, detail="Verified school email required")
    request.session.clear()

    result = await db.execute(select(User).where(User.oidc_issuer == issuer, User.oidc_subject == subject))
    user = result.scalar_one_or_none()
    if user is None:
        existing_email = await db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Ask an administrator to link your school account")
        user = User(
            email=email,
            username=claims.get("name") or claims.get("preferred_username") or email,
            password_hash="",
            oidc_issuer=issuer,
            oidc_subject=subject,
            role="student",
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Account provisioning conflict; try signing in again")

    response = RedirectResponse("/" if user.role == "instructor" else "/check-in", status_code=303)
    await auth.create_browser_session(response, user)
    return response

@app.get("/auth/me")
def whoami(context: auth.AuthContext = Depends(auth.require_auth)):
    return {"user_id": str(context.user.user_id), "email": context.user.email, "role": context.user.role, "csrf": context.csrf}

@app.post("/auth/logout")
async def logout(request: Request, context: auth.AuthContext = Depends(auth.require_auth)):
    response = RedirectResponse("/login", status_code=303)
    await auth.delete_browser_session(request, response)
    return response

@app.get("/courses")
async def list_courses(db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    result = await db.execute(select(Course).where(Course.user_id == context.user.user_id).order_by(Course.code, Course.course_name))
    return [records.course_json(course) for course in result.scalars()]

def make_qr_data_url(data: str) -> str:
    qr = qrcode.make(data)

    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")

    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"

@app.post("/session/start")
async def start_session(course_id: str, reload_time: int = token_store.RELOAD_TIME, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    if reload_time < 1:
        raise HTTPException(status_code=422, detail="reload_time must be at least 1 second")
    course = await owned_course(db, course_id, context.user)

    session = SessionModel(course_id=course.course_id, reload_time=reload_time)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    session_id = str(session.session_id)
    now = time.time()
    token_store.set_reload_time(session_id, reload_time)
    token_store.mark_session_active(session_id, now + reload_time)
    token_store.set_current_token(session_id, secrets.token_urlsafe(16), reload_time)
    metrics.SESSION_EVENTS.labels("start").inc()
    return {"session_id": session_id, "reload_time": reload_time}

@app.post("/session/end")
async def end_session(session_id: str, db: AsyncSession = Depends(get_session), context: auth.AuthContext = Depends(auth.require_instructor)):
    result = await owned_session(db, session_id, context.user, lock=True)
    result.status = "ended"
    result.ends_at = utcnow()
    await db.commit()
    token_store.mark_session_inactive(session_id)
    metrics.SESSION_EVENTS.labels("end").inc()
    return {"status": "ended"}
