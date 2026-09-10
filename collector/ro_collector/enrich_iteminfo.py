"""Load in-game item descriptions from the local game client into the DB.

Reads System/itemInfo_pro.lub from the game client install (plain-text Lua, the
authoritative in-game tooltip text incl. server customs), and upserts a
description for every item that exists in our data. Fully offline, no login,
runs in seconds — rerun after client patches to pick up changes.

    python -m ro_collector.enrich_iteminfo [--client-dir C:\\Gamez\\the server]
"""
import argparse
import logging
import pathlib
import sys

from .config import load_settings
from .db import Store
from .parse_iteminfo import parse_item_info_lua

log = logging.getLogger("ro.iteminfo")

DEFAULT_CLIENT_DIR = r"C:\Gamez\the server"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-dir", default=DEFAULT_CLIENT_DIR)
    args = ap.parse_args()

    lub = pathlib.Path(args.client_dir) / "System" / "itemInfo_pro.lub"
    if not lub.exists():
        raise SystemExit(f"not found: {lub} — pass --client-dir <client install dir>")
    descs = parse_item_info_lua(lub.read_text(encoding="cp949", errors="replace"))
    log.info("client file: %d item descriptions", len(descs))

    s = load_settings()
    store = Store(s.database_url)
    ids = ({l.item_id for l in store.latest_listings()}
           | {b.item_id for b in store.latest_buy_orders()}
           | {d["item_id"] for d in store.all_drops()})
    matched = {item_id: descs[item_id] for item_id in ids if item_id in descs}
    store.upsert_item_descriptions(matched)
    log.info("descriptions stored for %d/%d items in our data", len(matched), len(ids))


if __name__ == "__main__":
    main()
