import uuid
from http.cookies import SimpleCookie

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app import auth
from app.models import User


class FakeRedis:
    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


class FakeDb:
    def __init__(self, user):
        self.user = user

    async def get(self, model, user_id):
        return self.user if user_id == self.user.user_id else None


def request(method, cookie, csrf=None):
    headers = [(b"cookie", cookie.encode())]
    if csrf is not None:
        headers.append((b"x-csrf-token", csrf.encode()))
    return Request({"type": "http", "method": method, "path": "/", "headers": headers})


@pytest.mark.asyncio
async def test_browser_session_requires_csrf_and_can_be_revoked(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(auth, "redis_client", fake_redis)
    user = User(user_id=uuid.uuid4(), email="teacher@example.edu", username="Teacher", password_hash="", role="instructor")
    response = Response()
    csrf = await auth.create_browser_session(response, user)
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    cookie_header = f"{auth.COOKIE_NAME}={cookie[auth.COOKIE_NAME].value}"

    context = await auth.optional_auth(request("GET", cookie_header), FakeDb(user))
    assert context.user.user_id == user.user_id
    assert (await auth.require_instructor(context)).user == user

    with pytest.raises(HTTPException) as error:
        await auth.optional_auth(request("POST", cookie_header), FakeDb(user))
    assert error.value.status_code == 403

    context = await auth.optional_auth(request("POST", cookie_header, csrf), FakeDb(user))
    assert context.user.user_id == user.user_id

    await auth.delete_browser_session(request("POST", cookie_header, csrf), Response())
    assert await auth.optional_auth(request("GET", cookie_header), FakeDb(user)) is None


@pytest.mark.asyncio
async def test_student_cannot_use_instructor_access():
    student = User(user_id=uuid.uuid4(), email="student@example.edu", username="Student", password_hash="", role="student")
    with pytest.raises(HTTPException) as error:
        await auth.require_instructor(auth.AuthContext(user=student, csrf="example"))
    assert error.value.status_code == 403
