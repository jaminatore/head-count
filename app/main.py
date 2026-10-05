import os, qrcode, base64, io, asyncio, secrets, time, logging
import uuid

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from dotenv import load_dotenv

from app.scans import validate_scan
from app.db import init_db, get_session
from app import metrics

import app.tokens as token_store

load_dotenv()

from contextlib import asynccontextmanager
from app.models import Session as SessionModel
from app.models import utcnow # cause I'm lazy and don't want to redefine it

INSTANCE_ID = os.environ.get("HOSTNAME", "local")
SESSION_TIME = 30
logger = logging.getLogger(__name__)

class ScanRequest(BaseModel):
    token: str
    student: str
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
async def scan(payload: ScanRequest, db: AsyncSession = Depends(get_session)):
    try:
        valid, message, result = await validate_scan(payload.token, payload.student, payload.session, db)
    except Exception:
        metrics.SCANS.labels("error").inc()
        raise
    metrics.SCANS.labels(result).inc()
    return {"valid": valid, "message": message}

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
def current(session_id: str):
    if not token_store.is_session_active(session_id):
        return {"active": False}
    token = token_store.get_current_token(session_id)
    if token is None:
        return {"active": False}
    return {"active": True, "token": token, "qr": make_qr_data_url(f"{session_id}:{token}")}

@app.get("/healthz")
def healthz():
    return {"status": "ok",
            "instance": INSTANCE_ID}

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "admin.html", {"instance": INSTANCE_ID, "qr": ""})

def make_qr_data_url(data: str) -> str:
    qr = qrcode.make(data)

    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")

    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"

@app.post("/session/start")
async def start_session(course_id: str, reload_time: int = token_store.RELOAD_TIME, db: AsyncSession = Depends(get_session)):
    if reload_time < 1:
        return {"status": "error", "message": "reload_time must be at least 1 second"}

    session = SessionModel(course_id=course_id, reload_time=reload_time)
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
async def end_session(session_id: str, db: AsyncSession = Depends(get_session)):
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return {"status": "error", "message": "Invalid session id"}
    result = await db.get(SessionModel, session_uuid)
    if result:
        result.status = "ended"
        result.ends_at = utcnow()
        await db.commit()
    token_store.mark_session_inactive(session_id)
    metrics.SESSION_EVENTS.labels("end").inc()
    return {"status": "ended"}
