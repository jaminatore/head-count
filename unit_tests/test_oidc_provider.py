from urllib.parse import parse_qs, urlparse

from authlib.jose import jwt
from fastapi.testclient import TestClient

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
