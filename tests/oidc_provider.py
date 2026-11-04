"""Disposable OIDC issuer for the isolated end-to-end Compose stack only."""

import base64
import secrets
import time
from urllib.parse import parse_qs, urlencode

from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse


ISSUER = "http://oidc:9000"
CLIENT_ID = "headcount-e2e"
CLIENT_SECRET = "e2e-secret-not-for-production"
REDIRECT_URI = "http://nginx/auth/callback"
USERS = {
    "teacher": ("e2e-teacher", "teacher@headcount.test", "Test Teacher"),
    "student": ("e2e-student", "student@headcount.test", "Test Student"),
}

private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private_pem = private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
public_pem = private_key.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)
public_jwk = JsonWebKey.import_key(public_pem, {"kid": "headcount-e2e-key"}).as_dict()
codes = {}
access_tokens = {}
app = FastAPI()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/select/{user}")
def select_user(user: str):
    if user not in USERS:
        raise HTTPException(404, "Unknown test user")
    response = JSONResponse({"selected": user})
    response.set_cookie("test_user", user, httponly=True, samesite="lax")
    return response


@app.get("/.well-known/openid-configuration")
def discovery():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
        "userinfo_endpoint": ISSUER + "/userinfo",
        "jwks_uri": ISSUER + "/jwks",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
    }


@app.get("/jwks")
def jwks():
    return {"keys": [public_jwk]}


@app.get("/authorize")
def authorize(request: Request):
    params = request.query_params
    user = request.cookies.get("test_user")
    if (params.get("client_id") != CLIENT_ID or params.get("redirect_uri") != REDIRECT_URI
            or params.get("response_type") != "code" or "openid" not in params.get("scope", "").split()
            or not params.get("state") or user not in USERS):
        raise HTTPException(400, "Invalid test authorization request")
    code = secrets.token_urlsafe(24)
    codes[code] = (user, params.get("nonce"), time.time() + 60)
    return RedirectResponse(REDIRECT_URI + "?" + urlencode({"code": code, "state": params["state"]}), status_code=302)


@app.post("/token")
async def token(request: Request):
    form = {key: values[0] for key, values in parse_qs((await request.body()).decode()).items()}
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Basic "):
        try:
            client_id, client_secret = base64.b64decode(auth_header[6:]).decode().split(":", 1)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(401, "Invalid client authentication")
    else:
        client_id, client_secret = form.get("client_id"), form.get("client_secret")
    if (client_id, client_secret) != (CLIENT_ID, CLIENT_SECRET):
        raise HTTPException(401, "Invalid client authentication")
    if form.get("grant_type") != "authorization_code" or form.get("redirect_uri") != REDIRECT_URI:
        raise HTTPException(400, "Invalid token request")
    code_data = codes.pop(form.get("code", ""), None)
    if code_data is None or code_data[2] < time.time():
        raise HTTPException(400, "Invalid or expired code")
    subject, email, name = USERS[code_data[0]]
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": subject,
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        "email": email,
        "email_verified": True,
        "name": name,
    }
    if code_data[1]:
        claims["nonce"] = code_data[1]
    access_token = secrets.token_urlsafe(24)
    access_tokens[access_token] = claims
    id_token = jwt.encode({"alg": "RS256", "kid": "headcount-e2e-key"}, claims, private_pem).decode()
    return JSONResponse({"access_token": access_token, "token_type": "Bearer", "expires_in": 300, "id_token": id_token})


@app.get("/userinfo")
def userinfo(request: Request):
    bearer = request.headers.get("authorization", "")
    claims = access_tokens.get(bearer.removeprefix("Bearer ")) if bearer.startswith("Bearer ") else None
    if claims is None:
        raise HTTPException(401, "Invalid access token")
    return claims
