import pytest

from app import auth


def test_production_config_rejects_unconfigured_sso(monkeypatch):
    monkeypatch.setattr(auth, "OIDC_CONFIGURED", False)
    with pytest.raises(RuntimeError, match="OIDC"):
        auth.validate_production_config()


def test_production_config_accepts_secure_settings(monkeypatch):
    monkeypatch.setattr(auth, "OIDC_CONFIGURED", True)
    monkeypatch.setattr(auth, "OIDC_METADATA_URL", "https://sso.school.edu/.well-known/openid-configuration")
    monkeypatch.setattr(auth, "OIDC_CLIENT_ID", "headcount")
    monkeypatch.setattr(auth, "OIDC_CLIENT_SECRET", "school-client-secret")
    monkeypatch.setattr(auth, "AUTH_SESSION_SECRET", "a" * 48)
    monkeypatch.setattr(auth, "PUBLIC_BASE_URL", "https://attendance.school.edu")
    monkeypatch.setattr(auth, "COOKIE_SECURE", True)
    monkeypatch.setenv("HEADCOUNT_DOMAIN", "attendance.school.edu")
    auth.validate_production_config()
    monkeypatch.setenv("HEADCOUNT_DOMAIN", "other.school.edu")
    with pytest.raises(RuntimeError, match="HEADCOUNT_DOMAIN"):
        auth.validate_production_config()
    monkeypatch.setenv("HEADCOUNT_DOMAIN", "attendance.school.edu")
    monkeypatch.setattr(auth, "COOKIE_SECURE", False)
    with pytest.raises(RuntimeError, match="secure cookies"):
        auth.validate_production_config()
