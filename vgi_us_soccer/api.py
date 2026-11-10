"""The connector's only HTTP boundary: a small, read-only, caching JSON client.

Three public upstreams are used. Every request flows through :func:`get_json`,
which applies timeouts, bounded retries with backoff for 429 and 5xx responses,
redirect following, an honest User-Agent, per-host request pacing, and a short
in-process response cache so one SQL query never re-fetches the same document.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from vgi_us_soccer import __version__

USER_AGENT = f"vgi-us-soccer/{__version__} (+https://github.com/Query-farm/vgi-us-soccer)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 30.0
QUERY_TIMEOUT = 120.0
MAX_CONCURRENT_REQUESTS = 4
MAX_CACHE_ENTRIES = 256

logger = logging.getLogger(__name__)
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

_MAX_AGE = re.compile(r"(?:^|[,\s])max-age=(\d+)", re.IGNORECASE)
_NO_STORE = re.compile(r"(?:^|[,\s])no-store(?:$|[,\s])", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Source:
    """One upstream API with its base URL, override variable, and politeness policy."""

    name: str
    label: str
    default_base_url: str
    env_var: str
    default_ttl: float
    max_ttl: float
    min_interval: float
    read_timeout: float = 30.0

    def base_url(self) -> str:
        """Return the API root, optionally overridden for hermetic tests."""
        return os.environ.get(self.env_var, self.default_base_url).rstrip("/")


MLS = Source(
    name="mls",
    label="MLS Stats API",
    default_base_url="https://stats-api.mlssoccer.com",
    env_var="US_SOCCER_MLS_BASE_URL",
    default_ttl=60.0,
    max_ttl=300.0,
    min_interval=0.1,
)
NWSL = Source(
    name="nwsl",
    label="NWSL Sports Data Platform",
    default_base_url="https://api-sdp.nwslsoccer.com/v1/nwsl/football",
    env_var="US_SOCCER_NWSL_BASE_URL",
    default_ttl=120.0,
    max_ttl=300.0,
    min_interval=0.1,
)
ASA = Source(
    name="asa",
    label="American Soccer Analysis API",
    default_base_url="https://app.americansocceranalysis.com/api/v1",
    env_var="US_SOCCER_ASA_BASE_URL",
    default_ttl=900.0,
    max_ttl=3600.0,
    min_interval=0.2,
    read_timeout=60.0,
)
SOURCES = (MLS, NWSL, ASA)


class UpstreamError(RuntimeError):
    """A failed response from one of the upstream APIs."""

    def __init__(self, source: Source, status: int, body: str) -> None:
        super().__init__(f"{source.label} returned HTTP {status}: {body[:400]}")
        self.status = status
        self.source = source


@dataclass(frozen=True, slots=True)
class JsonResponse:
    """Decoded JSON plus the freshness the connector may advertise for it.

    ``max_age`` is the upstream ``Cache-Control: max-age`` capped by the
    source's own ceiling, or ``None`` when the origin sent ``no-store`` or no
    freshness information. ``None`` responses are never advertised as cacheable
    to VGI clients; they are only de-duplicated briefly inside this process.
    """

    payload: Any
    max_age: int | None = None
    status: int = 200


# Tests install an ``httpx.MockTransport`` here and switch pacing off; production
# always uses the network with pacing on.
_transport: httpx.BaseTransport | None = None
PACING = True

_cache_lock = threading.Lock()
_cache: OrderedDict[str, tuple[float, JsonResponse]] = OrderedDict()
_pace_lock = threading.Lock()
_last_request: dict[str, float] = {}


def clear_cache() -> None:
    """Drop every cached response (used by tests and long-lived operators)."""
    with _cache_lock:
        _cache.clear()
    with _pace_lock:
        _last_request.clear()


def _cache_get(key: str) -> JsonResponse | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires, response = entry
        if expires <= time.monotonic():
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return response


def _cache_put(key: str, response: JsonResponse, ttl: float) -> None:
    if ttl <= 0:
        return
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl, response)
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)


def _pace(source: Source) -> None:
    """Keep at least ``min_interval`` seconds between requests to one upstream."""
    if not PACING:
        return
    with _pace_lock:
        now = time.monotonic()
        wait = _last_request.get(source.name, 0.0) + source.min_interval - now
        _last_request[source.name] = max(now, now + wait)
    if wait > 0:
        time.sleep(wait)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Return a bounded Retry-After delay or exponential backoff with jitter."""
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                delay = float(raw)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = -1.0
            if delay >= 0:
                return min(delay, MAX_RETRY_DELAY)
    base = min(0.25 * 2**attempt, MAX_RETRY_DELAY)
    return min(base + random.uniform(0, base * 0.25), MAX_RETRY_DELAY)


def _max_age(source: Source, header: str) -> int | None:
    if not header or _NO_STORE.search(header):
        return None
    match = _MAX_AGE.search(header)
    if not match:
        return None
    return min(int(match.group(1)), int(source.max_ttl))


def _send(
    source: Source,
    url: str,
    params: Mapping[str, str | int],
    *,
    client: httpx.Client,
    deadline: float,
) -> httpx.Response:
    """Issue one logical GET, retrying transport failures, 429, and 5xx."""
    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{source.label} query exceeded {QUERY_TIMEOUT:g} seconds")
        started = time.monotonic()
        try:
            if not _request_slots.acquire(timeout=remaining):
                raise TimeoutError(f"{source.label} query exceeded {QUERY_TIMEOUT:g} seconds")
            try:
                _pace(source)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{source.label} query exceeded {QUERY_TIMEOUT:g} seconds")
                response = client.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    timeout=httpx.Timeout(min(source.read_timeout, remaining), connect=min(10.0, remaining)),
                    follow_redirects=True,
                )
            finally:
                _request_slots.release()
        except httpx.TransportError:
            logger.warning(
                "upstream_transport_error source=%s url=%s attempt=%d duration_ms=%d",
                source.name,
                url,
                attempt + 1,
                round((time.monotonic() - started) * 1_000),
            )
            if attempt + 1 == MAX_ATTEMPTS:
                raise
            time.sleep(min(_retry_delay(None, attempt), max(0.0, deadline - time.monotonic())))
            continue
        logger.debug(
            "upstream_response source=%s url=%s status=%d attempt=%d duration_ms=%d",
            source.name,
            url,
            response.status_code,
            attempt + 1,
            round((time.monotonic() - started) * 1_000),
        )
        if response.status_code not in RETRYABLE_STATUSES or attempt + 1 == MAX_ATTEMPTS:
            return response
        delay = min(_retry_delay(response, attempt), max(0.0, deadline - time.monotonic()))
        logger.warning(
            "upstream_retry source=%s status=%d attempt=%d delay_seconds=%.3f",
            source.name,
            response.status_code,
            attempt + 1,
            delay,
        )
        time.sleep(delay)
    raise AssertionError("retry loop exited without a response")


def get_json(
    source: Source,
    path: str,
    params: Mapping[str, str | int] | None = None,
    *,
    ttl: float | None = None,
    not_found_ok: bool = False,
    client: httpx.Client | None = None,
    deadline: float | None = None,
) -> JsonResponse:
    """GET ``path`` from ``source`` and decode JSON, serving fresh cached copies.

    ``ttl`` overrides the source's default in-process freshness for slowly
    changing reference documents (competition and season lists). When
    ``not_found_ok`` is true an HTTP 404 becomes a ``JsonResponse`` with a
    ``None`` payload and status 404 instead of an error, for upstreams that use
    404 to mean "nothing published yet".
    """
    query = {key: value for key, value in (params or {}).items() if value is not None}
    url = f"{source.base_url()}/{path.lstrip('/')}"
    key = str(httpx.URL(url, params=query))
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if deadline is None:
        deadline = time.monotonic() + QUERY_TIMEOUT
    if client is None:
        with httpx.Client(timeout=TIMEOUT, transport=_transport) as owned:
            response = _send(source, url, query, client=owned, deadline=deadline)
    else:
        response = _send(source, url, query, client=client, deadline=deadline)

    if response.status_code == 404 and not_found_ok:
        result = JsonResponse(payload=None, max_age=None, status=404)
        _cache_put(key, result, source.default_ttl)
        return result
    if not response.is_success:
        raise UpstreamError(source, response.status_code, response.text)
    try:
        payload = response.json()
    except ValueError as error:
        raise UpstreamError(source, response.status_code, "response body is not JSON") from error

    max_age = _max_age(source, response.headers.get("cache-control", ""))
    result = JsonResponse(payload=payload, max_age=max_age, status=response.status_code)
    effective_ttl = ttl if ttl is not None else (max_age if max_age is not None else source.default_ttl)
    _cache_put(key, result, min(float(effective_ttl), source.max_ttl if ttl is None else float(ttl)))
    return result


def shortest_max_age(responses: list[JsonResponse]) -> int | None:
    """Return the shortest advertised freshness only when every response supplied one."""
    values = [response.max_age for response in responses]
    if not values or any(value is None for value in values):
        return None
    return min(value for value in values if value is not None)
