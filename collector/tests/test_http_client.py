import requests
import responses

from ro_collector.http_client import SessionExpired, RoClient

BASE = "https://example.com/cp/"


@responses.activate
def test_ensure_authed_succeeds_when_logout_link_present():
    responses.add(
        responses.GET, BASE, body='<a href="?module=account&action=logout">Log out</a>', status=200
    )

    c = RoClient("cookie-value-123", throttle_seconds=0)
    c.ensure_authed()

    req = responses.calls[0].request
    assert "module=merchant" in req.url and "action=vendors" in req.url and "p=1" in req.url
    assert "cookie-value-123" in req.headers["Cookie"]


@responses.activate
def test_ensure_authed_raises_session_expired_when_logout_link_absent():
    responses.add(responses.GET, BASE, body="<html>please log in</html>", status=200)

    c = RoClient("cookie-value-123", throttle_seconds=0)
    try:
        c.ensure_authed()
        assert False, "expected SessionExpired"
    except SessionExpired:
        pass


@responses.activate
def test_get_page_passes_params_and_throttles(monkeypatch):
    sleeps = []
    monkeypatch.setattr("ro_collector.http_client.time.sleep", lambda s: sleeps.append(s))
    responses.add(responses.GET, BASE, body="<html>page</html>", status=200)

    c = RoClient("cookie-value-123", throttle_seconds=1.0)
    c.get_page(module="merchant", action="vendors", p=2)
    c.get_page(module="merchant", action="vendors", p=3)

    assert "p=2" in responses.calls[0].request.url
    assert "p=3" in responses.calls[1].request.url
    assert any(s > 0 for s in sleeps)  # second call throttled


@responses.activate
def test_get_page_retries_429_with_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr("ro_collector.http_client.time.sleep", lambda s: sleeps.append(s))
    responses.add(responses.GET, BASE, status=429, headers={"Retry-After": "17"})
    responses.add(responses.GET, BASE, body="<html>page</html>", status=200)

    c = RoClient("cookie-value-123", throttle_seconds=0)
    result = c.get_page(module="merchant", action="vendors", p=1)

    assert result == "<html>page</html>"
    assert len(responses.calls) == 2
    assert 17 in sleeps


@responses.activate
def test_get_page_retries_429_without_retry_after_uses_backoff_schedule(monkeypatch):
    sleeps = []
    monkeypatch.setattr("ro_collector.http_client.time.sleep", lambda s: sleeps.append(s))
    responses.add(responses.GET, BASE, status=429)
    responses.add(responses.GET, BASE, body="<html>page</html>", status=200)

    c = RoClient("cookie-value-123", throttle_seconds=0)
    result = c.get_page(module="merchant", action="vendors", p=1)

    assert result == "<html>page</html>"
    assert len(responses.calls) == 2
    assert 15 in sleeps


@responses.activate
def test_get_page_raises_after_six_consecutive_429s(monkeypatch):
    sleeps = []
    monkeypatch.setattr("ro_collector.http_client.time.sleep", lambda s: sleeps.append(s))
    for _ in range(6):
        responses.add(responses.GET, BASE, status=429)

    c = RoClient("cookie-value-123", throttle_seconds=0)
    try:
        c.get_page(module="merchant", action="vendors", p=1)
        assert False, "expected requests.HTTPError"
    except requests.HTTPError:
        pass

    assert len(responses.calls) == 6
    assert sleeps == [15, 30, 60, 120, 240]
