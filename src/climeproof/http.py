"""HTTP client with a content-addressed raw-response cache.

Every successful response is stored under data/cache/<source>/<request-hash>.json together with
the canonical request and the time it was retrieved. That gives:

- reproducibility: rerunning from the cache (``offline=True``) yields byte-identical metrics,
  including `retrieved_at`, because providers read both from the cache entry;
- auditability: each metric's provenance carries the request and the sha256 of the raw body,
  which points at the exact cached file it was computed from.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class OfflineCacheMiss(RuntimeError):
    """Raised in offline mode when a request has no cached response."""


@dataclass(frozen=True)
class CachedResponse:
    text: str
    request: str
    retrieved_at: datetime
    sha256: str
    from_cache: bool

    def json(self) -> Any:
        return json.loads(self.text)


def _canonical(method: str, url: str, params: dict | None, body: Any) -> str:
    parts = [method.upper(), url]
    if params:
        parts.append(urlencode(sorted(params.items())))
    if body is not None:
        parts.append(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str))
    return " ".join(parts)


class CachedHttp:
    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str,
        timeout_s: int = 120,
        offline: bool = False,
        refresh: bool = False,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.offline = offline
        self.refresh = refresh
        self._local = threading.local()

    # --- public API -------------------------------------------------------------------------
    def get(self, source: str, url: str, params: dict | None = None) -> CachedResponse:
        return self._request(source, "GET", url, params=params)

    def post_json(self, source: str, url: str, payload: dict) -> CachedResponse:
        return self._request(source, "POST", url, json_body=payload)

    def post_form(
        self, source: str, url: str, data: dict, files: dict[str, tuple[str, bytes, str]]
    ) -> CachedResponse:
        """Multipart POST. File contents are part of the cache key (by hash)."""
        key_body = {
            "data": data,
            "files": {k: hashlib.sha256(v[1]).hexdigest() for k, v in files.items()},
        }
        return self._request(source, "POST", url, form=(data, files), key_body=key_body)

    # --- internals --------------------------------------------------------------------------
    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            retry = Retry(
                total=4,
                backoff_factor=1.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
            )
            s.mount("https://", HTTPAdapter(max_retries=retry))
            s.headers["User-Agent"] = self.user_agent
            self._local.session = s
        return s

    def _request(
        self,
        source: str,
        method: str,
        url: str,
        params: dict | None = None,
        json_body: dict | None = None,
        form: tuple[dict, dict] | None = None,
        key_body: Any = None,
    ) -> CachedResponse:
        canonical = _canonical(method, url, params, key_body if key_body is not None else json_body)
        cached = self.lookup(source, canonical)
        if cached is not None:
            return cached
        if self.offline:
            raise OfflineCacheMiss(f"no cached response for: {canonical[:200]}")

        kwargs: dict[str, Any] = {"timeout": self.timeout_s}
        if params:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["json"] = json_body
        if form is not None:
            kwargs["data"], kwargs["files"] = form
        resp = self._session().request(method, url, **kwargs)
        resp.raise_for_status()
        return self.store(source, canonical, resp.text)

    # --- cache primitives (also used directly by non-HTTP sources, e.g. gridded stores) -----
    def _path(self, source: str, request: str) -> Path:
        return self.cache_dir / source / f"{hashlib.sha256(request.encode()).hexdigest()}.json"

    def lookup(self, source: str, request: str) -> CachedResponse | None:
        path = self._path(source, request)
        if self.refresh or not path.exists():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        return CachedResponse(
            text=entry["body"],
            request=entry["request"],
            retrieved_at=datetime.fromisoformat(entry["retrieved_at"]),
            sha256=entry["sha256"],
            from_cache=True,
        )

    def store(self, source: str, request: str, body: str) -> CachedResponse:
        entry = {
            "request": request,
            "retrieved_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "body": body,
        }
        _atomic_write(self._path(source, request), json.dumps(entry, ensure_ascii=False))
        return CachedResponse(
            text=body,
            request=request,
            retrieved_at=datetime.fromisoformat(entry["retrieved_at"]),
            sha256=entry["sha256"],
            from_cache=False,
        )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
