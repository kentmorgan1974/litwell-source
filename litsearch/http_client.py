# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
"""Shared HTTP access with polite rate limiting and retry/backoff.

Every network call in the app goes through :func:`get` so that error
handling and throttling live in exactly one place.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

import requests

from . import __version__

USER_AGENT = f"litsearch/{__version__} (literature search desktop tool)"

# Conservative default spacing between requests to the same host. NCBI allows
# 3 requests/second without an API key; Crossref asks for politeness too.
_MIN_INTERVAL = 0.4
_last_call_at: Dict[str, float] = {}


class NetworkError(RuntimeError):
    """Raised when a request ultimately fails after all retries."""


def _throttle(host: str, min_interval: float) -> None:
    now = time.monotonic()
    last = _last_call_at.get(host, 0.0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call_at[host] = time.monotonic()


def get(
    url: str,
    params: Optional[Dict[str, str]] = None,
    *,
    timeout: float = 30.0,
    max_retries: int = 4,
    min_interval: float = _MIN_INTERVAL,
    session: Optional[requests.Session] = None,
    headers: Optional[Dict[str, str]] = None,
) -> requests.Response:
    """GET ``url`` with retries on transient failures.

    Retries on connection errors, timeouts, HTTP 429 and 5xx responses,
    using exponential backoff (1s, 2s, 4s, 8s ...). Honors a ``Retry-After``
    header when the server sends one. Raises :class:`NetworkError` if every
    attempt fails.
    """
    sess = session or requests
    host = requests.utils.urlparse(url).netloc
    last_exc: Optional[Exception] = None
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)

    for attempt in range(max_retries + 1):
        _throttle(host, min_interval)
        try:
            resp = sess.get(
                url,
                params=params,
                timeout=timeout,
                headers=req_headers,
            )
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if resp.status_code < 400:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = NetworkError(
                    f"HTTP {resp.status_code} from {host}"
                )
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if retry_after is not None and retry_after > _MAX_WAIT:
                    # A budget/quota lockout (minutes-to-hours). Sleeping would
                    # freeze the app, so fail fast with the server's explanation.
                    raise NetworkError(_rate_limit_message(host, retry_after, resp))
                if attempt < max_retries:
                    time.sleep(retry_after if retry_after is not None else 2 ** attempt)
                    continue
            elif resp.status_code in (401, 403):
                raise NetworkError(
                    f"{host} refused the request: HTTP {resp.status_code} "
                    f"(missing or invalid API key)."
                )
            else:
                # 4xx other than 429: a bad query, not worth retrying.
                snippet = (resp.text or "").strip().replace("\n", " ")[:160]
                raise NetworkError(
                    f"Request to {host} failed: HTTP {resp.status_code}. "
                    f"Check your search terms and try again."
                    + (f" ({snippet})" if snippet else "")
                )

        if attempt < max_retries:
            time.sleep(2 ** attempt)

    raise NetworkError(
        f"Could not reach {host} after {max_retries + 1} attempts. "
        f"Check your internet connection. ({last_exc})"
    )


def post(
    url: str,
    *,
    data: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    max_retries: int = 2,
) -> requests.Response:
    """POST with the same backoff behavior as :func:`get`. Used for OAuth
    token requests."""
    host = requests.utils.urlparse(url).netloc
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    last_exc: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        _throttle(host, _MIN_INTERVAL)
        try:
            resp = requests.post(url, data=data, headers=req_headers, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if resp.status_code < 400:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            snippet = (resp.text or "").strip().replace("\n", " ")[:160]
            raise NetworkError(
                f"POST {host} failed: HTTP {resp.status_code}."
                + (f" ({snippet})" if snippet else "")
            )
        if attempt < max_retries:
            time.sleep(2 ** attempt)

    raise NetworkError(f"Could not reach {host}. ({last_exc})")


_MAX_WAIT = 30.0  # longest Retry-After we will actually sleep through (seconds)


def _rate_limit_message(host: str, seconds: float, resp: requests.Response) -> str:
    hrs, rem = divmod(int(seconds), 3600)
    when = f"{hrs}h {rem // 60}m" if hrs else f"{max(1, rem // 60)} min"
    detail = ""
    try:
        detail = str(resp.json().get("message", ""))[:260]
    except ValueError:
        detail = (resp.text or "").strip().replace("\n", " ")[:160]
    return (
        f"{host} rate limit reached — try again in about {when}."
        + (f" {detail}" if detail else "")
    )


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
