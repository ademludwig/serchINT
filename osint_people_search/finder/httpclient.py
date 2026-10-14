"""Polite HTTP client.

Enforces: HTTPS-only host allowlist, minimum interval per host, hard request
budget, timeouts, response-size cap, no redirects, and a host-wide pause after
HTTP 429 (honouring Retry-After when given in seconds).

NOTE: state is in-process. With a single worker (our default) that is enough;
with several workers you would need a shared limiter (e.g. Redis).
"""
import threading
import time
from urllib.parse import urlparse

import requests


class FetchError(Exception):
    """Base class for network-layer problems."""


class RateLimited(FetchError):
    def __init__(self, host, retry_after):
        super().__init__(f"{host} is rate-limiting us; paused for {retry_after:.0f}s")
        self.host = host
        self.retry_after = retry_after


class BudgetExceeded(FetchError):
    pass


class HostNotAllowed(FetchError):
    pass


class ResponseTooLarge(FetchError):
    pass


class RequestBudget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0

    def consume(self):
        if self.used >= self.limit:
            raise BudgetExceeded(f"request budget of {self.limit} exhausted")
        self.used += 1


DEFAULT_BACKOFF = 60.0
MAX_BACKOFF = 3600.0


def parse_retry_after(value):
    """Seconds form only; HTTP-date form falls back to the default pause."""
    try:
        return min(max(float(value), 1.0), MAX_BACKOFF)
    except (TypeError, ValueError):
        return DEFAULT_BACKOFF


class PoliteClient:
    def __init__(self, allowed_hosts, user_agent, min_interval=3.0, max_bytes=1_000_000,
                 timeout=(3, 10), budget=None, session=None,
                 clock=time.monotonic, sleep=time.sleep):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.min_interval = min_interval
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.budget = budget
        self._clock = clock
        self._sleep = sleep
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self._last_request = {}
        self._blocked_until = {}
        self._lock = threading.Lock()  # one request at a time

    def get(self, url, params=None):
        parsed = urlparse(url)
        host = parsed.hostname
        if parsed.scheme != "https" or host not in self.allowed_hosts:
            raise HostNotAllowed(f"refusing to fetch {url!r}")

        with self._lock:
            remaining = self._blocked_until.get(host, 0) - self._clock()
            if remaining > 0:
                raise RateLimited(host, remaining)  # no request is sent

            if self.budget is not None:
                self.budget.consume()

            last = self._last_request.get(host)
            if last is not None:
                wait = self.min_interval - (self._clock() - last)
                if wait > 0:
                    self._sleep(wait)

            response = None
            try:
                response = self._session.get(url, params=params, timeout=self.timeout,
                                             allow_redirects=False, stream=True)
                status = response.status_code
                if status == 429:
                    delay = parse_retry_after(response.headers.get("Retry-After"))
                    self._blocked_until[host] = self._clock() + delay
                    raise RateLimited(host, delay)
                if 300 <= status < 400:
                    raise FetchError(f"redirect from {host} refused")
                if status >= 400:
                    raise FetchError(f"HTTP {status} from {host}")

                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > self.max_bytes:
                    raise ResponseTooLarge(f"{host} response exceeds {self.max_bytes} bytes")

                chunks, size = [], 0
                for chunk in response.iter_content(16_384):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ResponseTooLarge(f"{host} response exceeds {self.max_bytes} bytes")
                    chunks.append(chunk)
                return b"".join(chunks)
            except requests.RequestException as exc:
                raise FetchError(f"request to {host} failed: {exc}") from exc
            finally:
                self._last_request[host] = self._clock()
                if response is not None:
                    response.close()
