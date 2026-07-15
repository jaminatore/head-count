import os, qrcode, base64, io, asyncio, secrets, time

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from dotenv import load_dotenv

from app.tokens import set_current_token, get_current_token, RELOAD_TIME
from app.scans import validate_scan
from app.db import init_db, get_session

load_dotenv()

from contextlib import asynccontextmanager

INSTANCE_ID = os.environ.get("HOSTNAME", "local")
SESSION_TIME = 30

# Probably want to remove this dict if it's the only state - we can change this to a global var later on
STATE = {"ends_at": None}

class ScanRequest(BaseModel):
    token: str
    student: str
    session: str


async def rotate_tokens():
    while True:
        token = secrets.token_urlsafe(16)
        set_current_token(token)
        await asyncio.sleep(RELOAD_TIME)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(rotate_tokens())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.post("/session/start")
def start_session():
    STATE["ends_at"] = time.time() + SESSION_TIME
    return {"ends_at": STATE["ends_at"]}

@app.post("/scan")
async def scan(payload: ScanRequest, db: AsyncSession = Depends(get_session)):
    valid, message = await validate_scan(payload.token, payload.student, payload.session, db)
    return {"valid": valid, "message": message}

@app.get("/current")
def current():
    ends_at = STATE["ends_at"]
    token = get_current_token()
    if ends_at is None or time.time() > ends_at or token is None:
        return {"active": False}
    return {"active": True, "token": token, "qr": make_qr_data_url(token)}

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