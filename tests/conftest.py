import json
from pathlib import Path

import pytest
import requests

BASE_URL = "http://localhost:1234"
SEED_DATA_PATH = Path(__file__).parent.parent / "seed_data.json"


@pytest.fixture(scope="session", autouse=True)
def ensure_stack_running():
    """Fail fast with a clear message if docker compose isn't up, instead
    of every test timing out individually with a connection error."""
    try:
        r = requests.get(f"{BASE_URL}/healthz", timeout=3)
        r.raise_for_status()
    except Exception as e:
        pytest.exit(
            f"Could not reach {BASE_URL}/healthz — is `docker compose up` running?\n({e})",
            returncode=1,
        )


@pytest.fixture(scope="session")
def seed_data():
    """Ids created by seed.py. Run `python seed.py --reset` before the
    test session if this file doesn't exist yet or looks stale."""
    if not SEED_DATA_PATH.exists():
        pytest.exit(
            f"{SEED_DATA_PATH} not found — run `python seed.py --reset` before running tests.",
            returncode=1,
        )
    return json.loads(SEED_DATA_PATH.read_text())