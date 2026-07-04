import secrets

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import qrcode
import base64
import io

INSTANCE_ID = os.environ.get("INSTANCE_ID", "local")

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/healthz")
def healthz():
    return {"status": "ok123"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    token = secrets.token_urlsafe(16)
    qr = make_qr_data_url(token)
    return templates.TemplateResponse(request, "admin.html", {"instance": INSTANCE_ID, "token": token, "qr": qr})

def make_qr_data_url(data: str) -> str:
    qr = qrcode.make(data)

    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")

    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"