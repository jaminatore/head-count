import os, qrcode, base64, io, asyncio, secrets, time

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from dotenv import load_dotenv

from app.scans import validate_scan
from app.db import init_db, get_session

from app.tokens import (
    set_current_token, get_current_token,
    mark_session_active, mark_session_inactive, get_active_sessions,
    RELOAD_TIME,
)

load_dotenv()

from contextlib import asynccontextmanager
from app.models import Session as SessionModel
from app.models import utcnow # cause I'm lazy and don't want to redefine it rn

INSTANCE_ID = os.environ.get("HOSTNAME", "local")
SESSION_TIME = 30

class ScanRequest(BaseModel):
    token: str
    student: str
    session: str

async def rotate_tokens():
    while True:
        for session_id in get_active_sessions():
            set_current_token(session_id, secrets.token_urlsafe(16))
        await asyncio.sleep(RELOAD_TIME)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db() # With migrate now in compose.yml, this (should) do nothing important. But it's an extra check for safety
    task = asyncio.create_task(rotate_tokens())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.post("/session/start")
async def start_session(course_id: str, db: DBSession = Depends(get_session)):
    session = SessionModel(course_id=course_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    session_id = str(session.session_id)
    mark_session_active(session_id)
    set_current_token(session_id, secrets.token_urlsafe(16))
    return {"session_id": session_id}

@app.post("/scan")
async def scan(payload: ScanRequest, db: AsyncSession = Depends(get_session)):
    valid, message = await validate_scan(payload.token, payload.student, payload.session, db)
    return {"valid": valid, "message": message}

@app.get("/current")
def current(session_id: str):
    active_ids = {str(s) for s in get_active_sessions()}
    if session_id not in active_ids:
        return {"active": False}
    token = get_current_token(session_id)
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

@app.post("/session/end")
async def end_session(session_id: str, db: DBSession = Depends(get_session)):
    result = await db.get(SessionModel, session_id)
    if result:
        result.status = "ended"
        result.ends_at = utcnow()
        await db.commit()
    mark_session_inactive(session_id)
    return {"status": "ended"}