"""Browser-backed transport with the same interface as RoClient.

The server puts a Cloudflare managed-challenge on the merchant pagination (p>1)
that only a real browser on a residential IP clears. This client drives real
Chrome via Playwright so the existing scrape pipeline (run_daily.run) works
unchanged — it only calls get_page(**params) and ensure_authed().

A persistent Chrome profile keeps both the FluxCP session and the Cloudflare
clearance warm between runs, so after the first authenticated run there is
usually no cookie to re-paste.
"""
import logging
import time

from playwright.sync_api import sync_playwright

from ro_collector.config import cp_domain, cp_url

log = logging.getLogger("ro.playwright")


class SessionExpired(RuntimeError):
    pass


class PlaywrightClient:
    @property
    def BASE(self) -> str:
        return cp_url()

    def __init__(self, session_cookie: str, profile_dir: str, throttle_seconds: float = 1.5,
                 headless: bool = False):
        self.session_cookie = session_cookie
        self.profile_dir = profile_dir
        self.throttle_seconds = throttle_seconds
        self.headless = headless
        self._pw = None
        self._ctx = None
        self._page = None
        self._last = 0.0

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            channel="chrome",
            headless=self.headless,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Seed the FluxCP session cookie so we're authed without an interactive
        # login. Harmless if the persistent profile is already logged in.
        if self.session_cookie:
            self._ctx.add_cookies([{
                "name": "fluxSessionData", "value": self.session_cookie,
                "domain": cp_domain(), "path": "/",
            }])
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()

    def _goto(self, params: dict) -> str:
        wait = self.throttle_seconds - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        self._page.goto(f"{self.BASE}?{qs}", wait_until="domcontentloaded", timeout=60000)
        # Give a Cloudflare challenge, if any, time to clear - auto (managed) or
        # a human clicking the "verify" box. Instant when there is no challenge
        # (loop breaks on the first check), patient (up to 60s) when there is.
        # page.content() raises if a redirect is mid-flight - retry, don't die
        # (killed a 2,375-page crawl at page 1,200 once).
        html = ""
        for _ in range(14):
            try:
                html = self._page.content()
            except Exception:
                self._page.wait_for_timeout(1000)
                continue
            if "Just a moment" not in html:
                break
            self._page.wait_for_timeout(5000)
        self._last = time.monotonic()
        return html

    def ensure_authed(self) -> None:
        html = self._goto({"module": "merchant", "action": "vendors", "p": 1})
        if "Just a moment" in html:
            raise SessionExpired(
                "Cloudflare challenge did not clear — is Chrome closed, or the IP flagged?")
        if "action=logout" not in html:
            raise SessionExpired(
                "server session expired — log into the CP in the scraper's Chrome "
                "profile (or refresh RO_SESSION_COOKIE).")

    def get_page(self, **params) -> str:
        return self._goto(params)
