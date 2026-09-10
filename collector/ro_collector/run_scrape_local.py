"""The 'collect fresh data' button: browser-backed daily scrape + shortlist.

Runs on a residential PC (real Chrome via Playwright) because the server's merchant
pagination is Cloudflare-gated. Reuses run_daily.run unchanged — PlaywrightClient
is a drop-in for RoClient. Prints the shortlist at the end so one click gets you
from 'go' to 'where do I farm tonight'.
"""
import logging
import pathlib

from . import report, run_daily, shortlist
from .config import load_settings
from .db import Store
from .overrides import apply_drop_overrides
from .playwright_client import PlaywrightClient

PROFILE_DIR = str(pathlib.Path(__file__).resolve().parents[1] / ".ro-profile")


def main() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # em dash / arrow glyphs on Windows consoles
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = load_settings()
    store = Store(s.database_url)
    with PlaywrightClient(s.session_cookie, PROFILE_DIR, throttle_seconds=1.5) as client:
        client.ensure_authed()
        run_daily.run(client, store)

    print("\n" + "=" * 70 + "\n")
    print(shortlist.build_report(
        store.latest_listings(),
        store.latest_buy_orders(),
        store.sales_since(shortlist.SALES_WINDOW_DAYS),
        apply_drop_overrides(store.all_drops()),
        store.farm_spots(),
        store.turnins(),
        s.char_level,
        store.monster_meta_all(),
        store.best_spawns(),
    ))

    # Build + open the visual dashboard (the explorable view).
    report.main()


if __name__ == "__main__":
    main()
