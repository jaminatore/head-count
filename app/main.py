import secrets
import time

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import qrcode
import base64
import io
import asyncio
from contextlib import asynccontextmanager

INSTANCE_ID = os.environ.get("INSTANCE_ID", "local")
SESSION_TIME = 20
RELOAD_TIME = 5

STATE = {
    "live_token": None,
    "ends_at": None,
}

async def rotate_tokens():
    while True:
        STATE["live_token"] = secrets.token_urlsafe(16)
        await asyncio.sleep(RELOAD_TIME)

@asynccontextmanager
async def lifespan(app: FastAPI):
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

@app.get("/current")
def current():
    ends_at = STATE["ends_at"]
    token = STATE["live_token"]
    if ends_at is None or time.time() > ends_at or token is None:
        return {"active": False}
    return {"active": True, "token": token, "qr": make_qr_data_url(token)}

@app.get("/healthz")
def healthz():
    return {"status": "ok123"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "admin.html", {"instance": INSTANCE_ID, "qr": ""})

def make_qr_data_url(data: str) -> str:
    qr = qrcode.make(data)

    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")

    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"