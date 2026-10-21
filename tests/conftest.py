from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest

from climeproof.config import load_settings
from climeproof.http import CachedResponse

FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)


class FakeHttp:
    """Stands in for CachedHttp. `handler(method, url, params_or_payload)` returns a body
    (str, or anything JSON-serialisable)."""

    offline = False

    def __init__(self, handler: Callable[[str, str, dict], object]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, dict]] = []
        self.memo: dict[str, CachedResponse] = {}

    def _resp(self, request: str, body) -> CachedResponse:
        text = body if isinstance(body, str) else json.dumps(body)
        return CachedResponse(
            text=text,
            request=request,
            retrieved_at=FIXED_TIME,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            from_cache=False,
        )

    def get(self, source, url, params=None):
        self.calls.append(("GET", url, params or {}))
        return self._resp(f"GET {url}", self.handler("GET", url, params or {}))

    def post_json(self, source, url, payload):
        self.calls.append(("POST", url, payload))
        return self._resp(f"POST {url}", self.handler("POST", url, payload))

    def lookup(self, source, request):
        return self.memo.get(request)

    def store(self, source, request, body):
        self.memo[request] = self._resp(request, body)
        return self.memo[request]


TODAY = date(2026, 10, 16)  # -> recent 2011-2025, trend 1996-2025, records through 2026-10-15


@pytest.fixture
def settings(tmp_path):
    s = load_settings(today=TODAY)
    s.pipeline.cache_dir = str(tmp_path / "cache")
    s.pipeline.workers = 1
    return s
