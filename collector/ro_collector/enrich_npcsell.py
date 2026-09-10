"""Load NPC sell prices: Hercules mainline + the server's documented overrides.

Mainline item_db.conf gives sell = explicit Sell or floor(Buy/2). The server then
customizes some shop prices, documented at the server wiki: Modified_Sales_Prices
(the page that would have saved the player 50k on Khukris: 120k mainline vs 25k
server-true). Overrides are matched by item name AND original price, so name
collisions can't misfire. Rerun occasionally / after server patch notes.

    python -m ro_collector.enrich_npcsell
"""
import logging
import sys

import requests

from .config import load_settings, wiki_url
from .db import Store
from .parse_itemdb import parse_item_names, parse_npc_sell
from .parse_wiki import parse_modified_sales

log = logging.getLogger("ro.npcsell")

ITEM_DB_URL = "https://raw.githubusercontent.com/HerculesWS/Hercules/master/db/pre-re/item_db.conf"
WIKI_SALES_URL = wiki_url() + "Modified_Sales_Prices/"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def apply_modified_sales(prices: dict[int, int], names: dict[int, str], rows: list[dict]) -> list[str]:
    """Mutate prices with the wiki overrides. An override applies to every id
    whose name matches AND whose mainline sell equals the wiki's 'original'
    price (disambiguates shared display names). Returns unmatched names."""
    by_name: dict[str, list[int]] = {}
    for item_id, name in names.items():
        by_name.setdefault(name.lower(), []).append(item_id)
    unresolved = []
    for row in rows:
        hits = [i for i in by_name.get(row["name"].lower(), []) if prices.get(i) == row["original"]]
        if not hits:
            unresolved.append(row["name"])
            continue
        for item_id in hits:
            prices[item_id] = row["modified"]
    return unresolved


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    r = requests.get(ITEM_DB_URL, timeout=60)
    r.raise_for_status()
    prices = parse_npc_sell(r.text)
    names = parse_item_names(r.text)
    log.info("mainline: %d NPC sell prices", len(prices))

    w = requests.get(WIKI_SALES_URL, headers=_UA, timeout=30)
    w.raise_for_status()
    rows = parse_modified_sales(w.text)
    unresolved = apply_modified_sales(prices, names, rows)
    log.info("wiki overrides: %d applied, unresolved: %s", len(rows) - len(unresolved), unresolved or "none")

    store = Store(load_settings().database_url)
    store.upsert_npc_sell(prices)
    log.info("stored")


if __name__ == "__main__":
    main()
