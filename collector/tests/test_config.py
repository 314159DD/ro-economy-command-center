import pytest


def test_load_settings_reads_env(monkeypatch):
    monkeypatch.setenv("RO_SESSION_COOKIE", "abc123sessioncookie")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("RO_CP_URL", "https://example.com/cp/")
    monkeypatch.setenv("RO_WIKI_URL", "https://example.com/wiki/")
    monkeypatch.delenv("CHAR_LEVEL", raising=False)
    monkeypatch.delenv("THROTTLE_SECONDS", raising=False)
    # Isolate from the developer's real collector/.env (which sets CHAR_LEVEL).
    monkeypatch.setattr("ro_collector.config.load_dotenv", lambda *a, **k: None)
    from ro_collector.config import load_settings

    s = load_settings()
    assert s.session_cookie == "abc123sessioncookie"
    assert s.database_url == "postgresql://x"
    assert s.char_level == 72  # default when CHAR_LEVEL unset
    assert s.throttle_seconds == 2.0


def test_load_settings_missing_vars_raises(monkeypatch):
    monkeypatch.delenv("RO_SESSION_COOKIE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Isolate from any real .env on disk (e.g. the developer's local collector/.env).
    monkeypatch.setattr("ro_collector.config.load_dotenv", lambda *a, **k: None)
    from ro_collector.config import ConfigError, load_settings

    with pytest.raises(ConfigError) as e:
        load_settings()
    assert "RO_SESSION_COOKIE" in str(e.value)
