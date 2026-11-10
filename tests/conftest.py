"""Shared fixtures: route every upstream request to recorded responses."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx
import pytest
from fixture_routes import CACHE_CONTROL, FIXTURES, resolve

from vgi_us_soccer import api

_HOSTS = {
    "stats-api.mlssoccer.com": ("mls", ""),
    "api-sdp.nwslsoccer.com": ("nwsl", "/v1/nwsl/football"),
    "app.americansocceranalysis.com": ("asa", "/api/v1"),
}


@dataclass
class Recorder:
    """Requests seen by the mock transport, for assertions on query parameters."""

    requests: list[httpx.Request] = field(default_factory=list)

    def paths(self) -> list[str]:
        """Return every requested URL path."""
        return [request.url.path for request in self.requests]

    def last(self, suffix: str) -> httpx.Request:
        """Return the most recent request whose path ends with ``suffix``."""
        return next(request for request in reversed(self.requests) if request.url.path.endswith(suffix))


def fixture_handler(recorder: Recorder):
    """Build a MockTransport handler serving recorded fixtures."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        source, prefix = _HOSTS[request.url.host]
        name = resolve(source, request.url.path.removeprefix(prefix))
        if name is None:
            return httpx.Response(404, json={"message": "Requested resource does not exist"})
        return httpx.Response(
            200,
            content=(FIXTURES / name).read_bytes(),
            headers={"Content-Type": "application/json", "Cache-Control": CACHE_CONTROL[source]},
        )

    return handler


@pytest.fixture(autouse=True)
def recorded_upstreams(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    """Serve fixtures for offline tests; live tests reach the real APIs."""
    api.clear_cache()
    recorder = Recorder()
    if request.node.get_closest_marker("live") is None:
        for source in api.SOURCES:
            monkeypatch.delenv(source.env_var, raising=False)
        monkeypatch.setattr(api, "_transport", httpx.MockTransport(fixture_handler(recorder)))
        monkeypatch.setattr(api, "PACING", False)
    yield recorder
    api.clear_cache()


def payload(name: str):
    """Return one decoded fixture."""
    return json.loads((FIXTURES / name).read_text())
