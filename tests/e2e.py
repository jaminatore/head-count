"""Black-box classroom journey through nginx, OIDC, app, Redis, and Postgres.

Run only with docker-compose.e2e.yml. The stack has no host ports and uses
disposable identities/data; no school credentials or production volumes.
"""

import csv
import io
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx


BASE = os.environ.get("HEADCOUNT_TEST_BASE_URL", "http://nginx")
OIDC = "http://oidc:9000"


def checked(response, status=200):
    assert response.status_code == status, f"{response.request.method} {response.request.url}: {response.status_code} {response.text[:500]}"
    return response


def sign_in(user):
    client = httpx.Client(base_url=BASE, follow_redirects=True, timeout=15)
    checked(client.get(f"{OIDC}/select/{user}"))
    checked(client.get("/auth/login"))
    identity = checked(client.get("/auth/me")).json()
    assert identity["email"] == f"{user}@headcount.test"
    client.headers["X-CSRF-Token"] = identity["csrf"]
    return client, identity


def current(client, session_id):
    data = checked(client.get("/current", params={"session_id": session_id})).json()
    assert data["active"] is True
    assert data["qr"].startswith("data:image/png;base64,")
    return data["token"]


def scan(client, session_id, token, **extra):
    return checked(client.post("/scan", json={"session": session_id, "token": token, **extra})).json()


def scan_current(student_client, teacher, session_id, **extra):
    for _ in range(4):
        result = scan(student_client, session_id, current(teacher, session_id), **extra)
        if result["result"] != "invalid_token":
            return result
    raise AssertionError("Live token rotated between display and scan four times")


def wait_for_rotation(client, session_id, previous, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        token = current(client, session_id)
        if token != previous:
            return token
        time.sleep(0.25)
    raise AssertionError("Token did not rotate on schedule")


def run():
    anonymous = httpx.Client(base_url=BASE, follow_redirects=False, timeout=10)
    assert checked(anonymous.get("/healthz")).json()["status"] == "ok"
    assert checked(anonymous.get("/readyz")).json()["status"] == "ready"
    checked(anonymous.get("/metrics"), 404)
    checked(anonymous.get("/courses"), 401)
    checked(anonymous.post("/scan", json={"session": str(uuid.uuid4()), "token": "fake"}), 401)
    print("PASS anonymous boundary and readiness", flush=True)

    outsider = httpx.Client(base_url=BASE, follow_redirects=True, timeout=15)
    checked(outsider.get(f"{OIDC}/select/outsider"))
    checked(outsider.get("/auth/login"), 403)
    checked(outsider.get("/auth/me"), 401)
    print("PASS OIDC hosted-domain restriction", flush=True)

    teacher, teacher_identity = sign_in("teacher")
    student, student_identity = sign_in("student")
    assert teacher_identity["role"] == "instructor"
    assert student_identity["role"] == "student"
    checked(teacher.get("/"))
    checked(student.get("/check-in"))
    checked(student.post("/courses", json={"course_name": "Forbidden", "code": "NO"}), 403)
    csrf = teacher.headers.pop("X-CSRF-Token")
    checked(teacher.post("/courses", json={"course_name": "Forbidden", "code": "NO"}), 403)
    teacher.headers["X-CSRF-Token"] = csrf
    print("PASS real OIDC redirect, roles, and CSRF", flush=True)

    suffix = uuid.uuid4().hex[:8].upper()
    courses = []
    for code in (f"A{suffix}", f"B{suffix}"):
        course = checked(teacher.post("/courses", json={"course_name": f"Test Course {code}", "code": code}), 201).json()
        courses.append(course)
        assert checked(student.post("/join", json={"join_code": course["join_code"]})).json()["status"] == "pending"
    course_a, course_b = courses
    roster = checked(teacher.get(f"/courses/{course_a['course_id']}/roster")).json()
    assert roster["students"][0]["status"] == "pending"
    assert roster["students"][0]["user_id"] == student_identity["user_id"]

    session_a = checked(teacher.post("/session/start", params={"course_id": course_a["course_id"], "reload_time": 4})).json()["session_id"]
    session_b = checked(teacher.post("/session/start", params={"course_id": course_b["course_id"], "reload_time": 30})).json()["session_id"]
    token_a = current(teacher, session_a)
    token_b = current(teacher, session_b)
    assert scan(student, session_a, token_a)["result"] == "not_enrolled"
    checked(student.post("/session/start", params={"course_id": course_a["course_id"]}), 403)
    for course in courses:
        result = checked(teacher.post(
            f"/courses/{course['course_id']}/enrollments/{student_identity['user_id']}",
            json={"status": "approved"},
        )).json()
        assert result["status"] == "approved"
    assert {item["status"] for item in checked(student.get("/my-courses")).json()} == {"approved"}
    print("PASS join request, instructor approval, and enrollment enforcement", flush=True)

    rotated_a = wait_for_rotation(teacher, session_a, token_a)
    assert current(teacher, session_b) == token_b
    assert scan(student, session_a, token_a)["result"] == "invalid_token"
    assert scan(student, session_b, rotated_a)["result"] == "invalid_token"
    assert scan(student, session_b, "forged")["result"] == "invalid_token"
    accepted = scan_current(student, teacher, session_a, student=str(uuid.uuid4()))
    assert accepted["result"] == "accepted" and accepted["valid"] is True
    assert scan_current(student, teacher, session_a)["result"] == "duplicate"
    print("PASS rotation, forgery rejection, identity binding, and duplicate scan", flush=True)

    # A separate session receives concurrent scans through the HTTP edge.
    token_b = current(teacher, session_b)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: scan(student, session_b, token_b)["result"], range(8)))
    assert results.count("accepted") == 1, results
    assert results.count("duplicate") == 7, results
    print("PASS concurrent exactly-once attendance", flush=True)

    attendance = checked(teacher.get(f"/sessions/{session_a}/attendance")).json()
    assert attendance["roster_count"] == attendance["present_count"] == 1
    assert attendance["students"][0]["user_id"] == student_identity["user_id"]
    checked(student.get(f"/sessions/{session_a}/attendance"), 403)
    checked(student.get(f"/sessions/{session_a}/export"), 403)
    checked(teacher.post(
        f"/sessions/{session_a}/attendance/{student_identity['user_id']}/void",
        json={"reason": "Test correction"},
    ))
    assert checked(teacher.get(f"/sessions/{session_a}/attendance")).json()["present_count"] == 0
    checked(teacher.post(
        f"/sessions/{session_a}/attendance/{student_identity['user_id']}",
        json={"reason": "Test restoration"},
    ))
    assert checked(teacher.get(f"/sessions/{session_a}/attendance")).json()["students"][0]["source"] == "manual"
    audit = checked(teacher.get(f"/sessions/{session_a}/audit")).json()
    events = {entry["event_type"] for entry in audit}
    assert {"accepted", "duplicate", "invalid_token", "manual_void", "manual_add"}.issubset(events), events
    exported = checked(teacher.get(f"/sessions/{session_a}/export"))
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 1 and rows[0]["student_id"] == student_identity["user_id"]
    assert rows[0]["present"] == "True" and rows[0]["source"] == "manual"
    print("PASS records, correction audit, ownership, and CSV", flush=True)

    checked(teacher.post("/session/end", params={"session_id": session_a}))
    checked(teacher.post("/session/end", params={"session_id": session_b}))
    assert checked(teacher.get("/current", params={"session_id": session_a})).json()["active"] is False
    assert scan(student, session_a, token_a)["result"] == "session_closed"
    metrics = checked(httpx.get("http://app:8000/metrics", timeout=10)).text
    assert "headcount_scans_total" in metrics and "headcount_rotator_last_iteration_timestamp_seconds" in metrics
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        targets = checked(httpx.get("http://prometheus:9090/api/v1/targets", timeout=10)).json()["data"]["activeTargets"]
        jobs = {target["labels"]["job"] for target in targets if target["health"] == "up"}
        if {"headcount-app", "redis", "postgres"}.issubset(jobs):
            break
        time.sleep(1)
    else:
        raise AssertionError(f"Prometheus targets unhealthy: {targets}")
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        query = checked(httpx.get("http://prometheus:9090/api/v1/query", params={"query": 'sum(headcount_scans_total{result="accepted"})'}, timeout=10)).json()
        result = query["data"]["result"]
        if result and float(result[0]["value"][1]) >= 2:
            break
        time.sleep(1)
    else:
        raise AssertionError(f"Prometheus did not scrape accepted scans: {query}")
    checked(student.post("/auth/logout"), 200)  # redirects are followed to /login
    checked(student.get("/my-courses"), 401)
    print("PASS session close, Prometheus scrape, and logout", flush=True)


if __name__ == "__main__":
    run()
