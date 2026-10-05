"""Black-box checks for the Prometheus path through the Compose stack."""

import time

import requests


APP_URL = "http://localhost:1234"
PROMETHEUS_URL = "http://localhost:9090"


def _scan_count():
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": 'sum(headcount_scans_total{result="invalid_token"})'},
        timeout=3,
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]
    return float(result[0]["value"][1]) if result else 0.0


def test_private_metrics_scraped_from_app_replicas():
    assert requests.get(f"{APP_URL}/metrics", timeout=3).status_code == 404

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/targets", timeout=3)
        response.raise_for_status()
        targets = response.json()["data"]["activeTargets"]
        jobs = {"headcount-app", "redis", "postgres"}
        if jobs.issubset({target["labels"]["job"] for target in targets}) and all(
            target["health"] == "up" for target in targets
        ):
            return
        time.sleep(1)
    raise AssertionError("Prometheus did not report healthy app, Redis, and Postgres targets")


def test_rejected_scan_reaches_prometheus():
    before = _scan_count()
    response = requests.post(
        f"{APP_URL}/scan",
        json={
            "token": "not-live",
            "student": "00000000-0000-0000-0000-000000000000",
            "session": "00000000-0000-0000-0000-000000000000",
        },
        timeout=3,
    )
    response.raise_for_status()
    assert response.json()["valid"] is False

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _scan_count() > before:
            return
        time.sleep(1)
    raise AssertionError("Prometheus did not observe the rejected scan")
