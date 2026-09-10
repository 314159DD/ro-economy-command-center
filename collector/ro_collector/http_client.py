"""Session-holding HTTP client for the FluxCP: replays a browser session cookie, throttled GETs."""
import logging
import time

import requests

from ro_collector.config import cp_domain, cp_url

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

log = logging.getLogger("ro.http")

# Backoff schedule (seconds) used when a 429 response has no Retry-After header.
RATE_LIMIT_BACKOFF = [15, 30, 60, 120, 240]
MAX_RATE_LIMIT_RETRIES = 5


class SessionExpired(RuntimeError):
    pass


class RoClient:
    @property
    def BASE(self) -> str:
        return cp_url()

    def __init__(self, session_cookie: str, throttle_seconds: float = 1.0):
        self.throttle_seconds = throttle_seconds
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.cookies.set("fluxSessionData", session_cookie, domain=cp_domain())
        self._last_request = 0.0

    def _throttled(self, method: str, url: str, **kw) -> requests.Response:
        attempt = 0
        while True:
            wait = self.throttle_seconds - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            resp = self.session.request(method, url, timeout=30, **kw)
            self._last_request = time.monotonic()
            if resp.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                attempt += 1
                retry_after = int(resp.headers.get("Retry-After", 0))
                backoff = retry_after if retry_after > 0 else RATE_LIMIT_BACKOFF[attempt - 1]
                log.warning(
                    "429 rate-limited, waiting %ss (attempt %s/%s)",
                    backoff, attempt, MAX_RATE_LIMIT_RETRIES,
                )
                time.sleep(backoff)
                continue
            resp.raise_for_status()
            return resp

    def ensure_authed(self) -> None:
        """Verify the replayed session cookie is still valid."""
        resp = self._throttled("GET", self.BASE, params={"module": "merchant", "action": "vendors", "p": 1})
        if "action=logout" not in resp.text:
            raise SessionExpired(
                "server session cookie expired — log in via browser and update RO_SESSION_COOKIE"
            )

    def get_page(self, **params) -> str:
        return self._throttled("GET", self.BASE, params=params).text
