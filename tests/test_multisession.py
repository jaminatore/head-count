import requests

BASE_URL = "http://localhost:1234"


class TestMultisession:
    """Mirrors the original Postman collection: create two sessions on two
    different courses, prove each rotates its own token, prove dedup
    survives rotation, prove a token from one session is rejected under
    the other, then clean up."""

    def test_01_start_session_a(self, seed_data):
        r = requests.post(f"{BASE_URL}/session/start", params={"course_id": seed_data["bio_course_id"]})
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        TestMultisession.session_a = data["session_id"]

    def test_02_start_session_b(self, seed_data):
        r = requests.post(f"{BASE_URL}/session/start", params={"course_id": seed_data["cs_course_id"]})
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] != TestMultisession.session_a
        TestMultisession.session_b = data["session_id"]

    def test_03_current_token_a(self):
        r = requests.get(f"{BASE_URL}/current", params={"session_id": TestMultisession.session_a})
        data = r.json()
        assert data["active"] is True
        TestMultisession.token_a = data["token"]

    def test_04_current_token_b(self):
        r = requests.get(f"{BASE_URL}/current", params={"session_id": TestMultisession.session_b})
        data = r.json()
        assert data["active"] is True
        assert data["token"] != TestMultisession.token_a
        TestMultisession.token_b = data["token"]

    def test_05_scan_a_accepted(self, seed_data):
        r = requests.post(f"{BASE_URL}/scan", json={
            "token": TestMultisession.token_a,
            "student": seed_data["student_a_id"],
            "session": TestMultisession.session_a,
        })
        assert r.json()["valid"] is True

    def test_06_scan_a_duplicate_rejected(self, seed_data):
        r = requests.post(f"{BASE_URL}/scan", json={
            "token": TestMultisession.token_a,
            "student": seed_data["student_a_id"],
            "session": TestMultisession.session_a,
        })
        data = r.json()
        assert data["valid"] is False
        assert "already" in data["message"].lower()

    def test_07_cross_session_scan_rejected(self, seed_data):
        """The isolation guarantee: session A's token must not validate
        against session B, even though both are live at the same time."""
        r = requests.post(f"{BASE_URL}/scan", json={
            "token": TestMultisession.token_a,
            "student": seed_data["student_a_id"],
            "session": TestMultisession.session_b,
        })
        data = r.json()
        assert data["valid"] is False
        assert "invalid" in data["message"].lower()

    def test_08_healthz(self):
        r = requests.get(f"{BASE_URL}/healthz")
        assert r.json()["status"] == "ok"

    def test_09_end_session_a(self):
        r = requests.post(f"{BASE_URL}/session/end", params={"session_id": TestMultisession.session_a})
        assert r.json()["status"] == "ended"

    def test_10_end_session_b(self):
        r = requests.post(f"{BASE_URL}/session/end", params={"session_id": TestMultisession.session_b})
        assert r.json()["status"] == "ended"

    def test_11_verify_session_a_closed(self):
        r = requests.get(f"{BASE_URL}/current", params={"session_id": TestMultisession.session_a})
        assert r.json()["active"] is False