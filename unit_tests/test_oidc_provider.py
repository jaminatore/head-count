from urllib.parse import parse_qs, urlparse

from authlib.jose import jwt
from fastapi.testclient import TestClient

from tests import oidc_provider
from tests.oidc_provider import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, app, public_jwk


def test_disposable_oidc_code_exchange():
    with TestClient(app) as client:
        assert client.get("/select/teacher").status_code == 200
        authorization = client.get("/authorize", params={
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "openid profile email",
            "state": "test-state",
            "nonce": "test-nonce",
        }, follow_redirects=False)
        assert authorization.status_code == 302
        code = parse_qs(urlparse(authorization.headers["location"]).query)["code"][0]
        response = client.post("/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }, auth=(CLIENT_ID, CLIENT_SECRET))
        assert response.status_code == 200, response.text
        claims = jwt.decode(response.json()["id_token"], {"keys": [public_jwk]})
        claims.validate()
        assert claims["sub"] == "e2e-teacher"
        assert claims["hd"] == "headcount.test"
        assert claims["nonce"] == "test-nonce"
        assert client.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI}, auth=(CLIENT_ID, CLIENT_SECRET)).status_code == 400


def test_local_mock_uses_browser_origin_and_login_redirect(monkeypatch):
    monkeypatch.setattr(oidc_provider, "AUTHORIZATION_ORIGIN", "http://localhost:9000")
    monkeypatch.setattr(oidc_provider, "LOGIN_URL", "http://localhost:1234/auth/login")
    with TestClient(app) as client:
        assert client.get("/.well-known/openid-configuration").json()["authorization_endpoint"] == "http://localhost:9000/authorize"
        response = client.get("/select/student", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "http://localhost:1234/auth/login"
        assert "test_user=student" in response.headers["set-cookie"]
