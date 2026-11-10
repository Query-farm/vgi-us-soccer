"""Tests for the connector's single HTTP boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from vgi_us_soccer import __version__, api


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(api.time, "sleep", recorded.append)
    return recorded


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(api, "_transport", httpx.MockTransport(handler))


def test_sends_honest_user_agent_and_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    _install(monkeypatch, handler)
    api.get_json(api.MLS, "competitions")
    assert seen[0].headers["user-agent"] == (
        f"vgi-us-soccer/{__version__} (+https://github.com/Query-farm/vgi-us-soccer)"
    )
    assert seen[0].headers["accept"] == "application/json"


def test_base_url_override_and_none_params_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("US_SOCCER_ASA_BASE_URL", "http://fixtures.test/asa/")
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=[])

    _install(monkeypatch, handler)
    api.get_json(api.ASA, "/mls/teams", {"season_name": 2025, "team_id": None})
    assert str(seen[0]) == "http://fixtures.test/asa/mls/teams?season_name=2025"


def test_retries_429_and_5xx_honoring_retry_after(monkeypatch: pytest.MonkeyPatch, sleeps) -> None:
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        headers = {"Retry-After": "2"} if status == 429 else {}
        return httpx.Response(status, json={"ok": status == 200}, headers=headers)

    _install(monkeypatch, handler)
    result = api.get_json(api.NWSL, "competitions")
    assert result.payload == {"ok": True}
    assert sleeps[0] == 2.0
    assert 0 < sleeps[1] <= api.MAX_RETRY_DELAY


def test_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch, sleeps) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502, text="bad gateway")

    _install(monkeypatch, handler)
    with pytest.raises(api.UpstreamError, match="NWSL Sports Data Platform returned HTTP 502"):
        api.get_json(api.NWSL, "competitions")
    assert calls == api.MAX_ATTEMPTS


def test_transport_errors_are_retried_then_raised(monkeypatch: pytest.MonkeyPatch, sleeps) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    _install(monkeypatch, handler)
    assert api.get_json(api.MLS, "competitions").payload == {"ok": True}

    def always_fails(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    api.clear_cache()
    _install(monkeypatch, always_fails)
    with pytest.raises(httpx.ReadTimeout):
        api.get_json(api.MLS, "competitions")


def test_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(307, headers={"Location": "https://stats-api.mlssoccer.com/new"})
        return httpx.Response(200, json={"path": request.url.path})

    _install(monkeypatch, handler)
    assert api.get_json(api.MLS, "old").payload == {"path": "/new"}


def test_caches_responses_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"n": calls}, headers={"Cache-Control": "max-age=86400"})

    _install(monkeypatch, handler)
    first = api.get_json(api.NWSL, "competitions", {"locale": "en-US"})
    second = api.get_json(api.NWSL, "competitions", {"locale": "en-US"})
    assert first is second
    assert calls == 1
    # Advertised freshness is capped by the source's own ceiling.
    assert first.max_age == int(api.NWSL.max_ttl)
    api.get_json(api.NWSL, "competitions", {"locale": "fr-FR"})
    assert calls == 2


def test_cache_entries_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"n": calls})

    _install(monkeypatch, handler)
    api.get_json(api.MLS, "competitions")
    clock[0] += api.MLS.default_ttl + 1
    assert api.get_json(api.MLS, "competitions").payload == {"n": 2}


def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda request: httpx.Response(200, json={}))
    for index in range(api.MAX_CACHE_ENTRIES + 5):
        api.get_json(api.MLS, f"matches/{index}")
    assert len(api._cache) == api.MAX_CACHE_ENTRIES


def test_no_store_is_never_advertised(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda request: httpx.Response(200, json={}, headers={"Cache-Control": "no-store"}))
    assert api.get_json(api.MLS, "competitions").max_age is None


def test_not_found_ok_returns_empty_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda request: httpx.Response(404, json={"message": "missing"}))
    result = api.get_json(api.MLS, "matches/MLS-MAT-XXXXXX", not_found_ok=True)
    assert result.payload is None
    assert result.status == 404
    api.clear_cache()
    with pytest.raises(api.UpstreamError, match="HTTP 404.*missing"):
        api.get_json(api.MLS, "matches/MLS-MAT-XXXXXX")


def test_non_json_body_is_an_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(api.UpstreamError, match="not JSON"):
        api.get_json(api.ASA, "mls/teams")


def test_deadline_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda request: httpx.Response(200, json={}))
    with pytest.raises(TimeoutError, match="exceeded"):
        api.get_json(api.MLS, "competitions", deadline=api.time.monotonic() - 1)


def test_explicit_client_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[1]))) as client:
        assert api.get_json(api.ASA, "mls/teams", client=client).payload == [1]


def test_retry_delay_parses_http_dates_and_bounds_backoff() -> None:
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    delay = api._retry_delay(httpx.Response(429, headers={"Retry-After": future}), 0)
    assert 0 <= delay <= 10.5
    assert api._retry_delay(httpx.Response(429, headers={"Retry-After": "9999"}), 0) == api.MAX_RETRY_DELAY
    garbage = api._retry_delay(httpx.Response(429, headers={"Retry-After": "soon"}), 2)
    assert 0 < garbage <= api.MAX_RETRY_DELAY
    assert api._retry_delay(None, 50) == api.MAX_RETRY_DELAY


def test_pacing_spaces_requests_to_one_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [50.0]
    slept: list[float] = []
    monkeypatch.setattr(api, "PACING", True)
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api.time, "sleep", slept.append)
    api._pace(api.ASA)
    api._pace(api.ASA)
    assert slept == [pytest.approx(api.ASA.min_interval)]


def test_shortest_max_age() -> None:
    assert api.shortest_max_age([]) is None
    assert api.shortest_max_age([api.JsonResponse({}, 60), api.JsonResponse({}, 30)]) == 30
    assert api.shortest_max_age([api.JsonResponse({}, 60), api.JsonResponse({}, None)]) is None
