import requests
import pytest

BASE_URL = "http://localhost:1234"


def test_instructor_page_has_session_controls():
    response = requests.get(BASE_URL, timeout=5)
    assert response.status_code == 200
    assert 'id="session-form"' in response.text
    assert 'id="course"' in response.text
    assert 'id="end"' in response.text


def test_courses_have_labels_for_picker():
    response = requests.get(f"{BASE_URL}/courses", timeout=5)
    assert response.status_code == 200
    courses = response.json()
    assert isinstance(courses, list)
    assert courses == sorted(courses, key=lambda course: (course["code"], course["course_name"]))
    for course in courses:
        assert set(course) == {"course_id", "course_name", "code"}


def test_instructor_session_flow():
    courses = requests.get(f"{BASE_URL}/courses", timeout=5).json()
    if not courses:
        pytest.skip("Seed a course to test the instructor session flow")

    response = requests.post(
        f"{BASE_URL}/session/start",
        params={"course_id": courses[0]["course_id"], "reload_time": 2},
        timeout=5,
    )
    response.raise_for_status()
    session_id = response.json()["session_id"]
    try:
        current = requests.get(f"{BASE_URL}/current", params={"session_id": session_id}, timeout=5)
        current.raise_for_status()
        assert current.json()["active"] is True
        assert current.json()["qr"].startswith("data:image/png;base64,")
    finally:
        ended = requests.post(f"{BASE_URL}/session/end", params={"session_id": session_id}, timeout=5)
        ended.raise_for_status()

    current = requests.get(f"{BASE_URL}/current", params={"session_id": session_id}, timeout=5)
    assert current.json()["active"] is False
