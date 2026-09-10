"""Crawl CP item view pages for in-game descriptions -> items table.

The item module needs a logged-in session (redirects to login otherwise) and
the fluxSessionData cookie is session-scoped — it dies when Chrome closes.
So this runs through the same persistent-profile Chrome as the daily scrape:
if the session is cold, the login page is shown and we wait for the player to
log in once, then crawl every item id in the report data that has no
description yet (~0.7s/page; first full run ~30-40 min, afterwards only new
items). Usage:

    python -m ro_collector.enrich_items [--limit N]
"""
import argparse
import logging
import sys
import time

from .config import cp_url, load_settings
from .db import Store
from .parse_item import parse_item_page
from .playwright_client import PlaywrightClient
from .run_scrape_local import PROFILE_DIR

log = logging.getLogger("ro.items")

LOGIN_WAIT_MINUTES = 10


def wait_for_login(client: PlaywrightClient) -> None:
    """If the profile session is cold, park on the login page until the player
    logs in (reCAPTCHA makes scripted login impossible)."""
    html = client.get_page(module="item", action="view", id=1734)
    if "action=logout" in html:
        return
    log.info("session cold — log into the control panel in the Chrome window (waiting up to %d min)",
             LOGIN_WAIT_MINUTES)
    client._page.goto(cp_url() + "?module=account&action=login",
                      wait_until="domcontentloaded", timeout=60000)
    deadline = time.monotonic() + LOGIN_WAIT_MINUTES * 60
    while time.monotonic() < deadline:
        time.sleep(5)
        try:
            if "action=logout" in client._page.content():
                log.info("logged in")
                return
        except Exception:
            continue  # mid-navigation
    raise SystemExit("timed out waiting for login")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="crawl at most N items (0 = all)")
    ap.add_argument("--all", action="store_true",
                    help="recrawl everything (verify mainline+wiki NPC prices against the CP)")
    args = ap.parse_args()

    s = load_settings()
    store = Store(s.database_url)
    ids = ({l.item_id for l in store.latest_listings()}
           | {b.item_id for b in store.latest_buy_orders()}
           | {d["item_id"] for d in store.all_drops()})
    todo = sorted(ids) if args.all else store.item_ids_missing_info(sorted(ids))
    log.info("%d items total, %d missing descriptions", len(ids), len(todo))
    if args.limit:
        todo = todo[: args.limit]
        log.info("limited to %d this run", len(todo))
    if not todo:
        return

    ok = missed = 0
    with PlaywrightClient(s.session_cookie, PROFILE_DIR, throttle_seconds=0.7) as client:
        wait_for_login(client)
        for n, item_id in enumerate(todo, 1):
            html = client.get_page(module="item", action="view", id=item_id)
            if "action=logout" not in html:
                raise SystemExit(f"session dropped after {n-1} items — rerun to continue")
            info = parse_item_page(html, item_id)
            if info:
                store.upsert_item_info(info)
                ok += 1
            else:
                missed += 1
            if n % 100 == 0:
                log.info("%d/%d (%d parsed, %d unparseable)", n, len(todo), ok, missed)
    log.info("done: %d parsed, %d unparseable", ok, missed)


if __name__ == "__main__":
    main()
