"""Monthly refresh: monster drop tables (server-true rates) + wiki turn-in quests."""
import logging

import requests

from .config import load_settings, wiki_url
from .db import Store
from .http_client import USER_AGENT, RoClient
from .models import Monster
from .parse_monster import parse_monster_index, parse_monster_page
from .parse_wiki import NPC_PURCHASABLE, parse_repeatable_quests

log = logging.getLogger("ro.refresh")
WIKI_URL = wiki_url() + "Repeatable_Quests/"


def run(client, store) -> None:
    # 1) monster index -> all rows (id/name/level/hp), deduped by id
    index_by_id: dict[int, dict] = {}
    page_rows, total = parse_monster_index(client.get_page(module="monster", p=1))
    for row in page_rows:
        index_by_id.setdefault(row["id"], row)
    pages = max(1, -(-total // 20))  # ceil
    for p in range(2, pages + 1):
        page_rows, _ = parse_monster_index(client.get_page(module="monster", p=p))
        for row in page_rows:
            index_by_id.setdefault(row["id"], row)
    ids = sorted(index_by_id)
    log.info("monster index: %s ids across %s pages", len(ids), pages)

    # 2) each monster view -> merge with index row -> upsert (batch per 50)
    batch = []
    for i, mid in enumerate(ids, 1):
        try:
            view = parse_monster_page(client.get_page(module="monster", action="view", id=mid), mid)
            index_row = index_by_id[mid]
            batch.append(
                Monster(
                    id=mid,
                    name=view.name or index_row["name"],
                    level=index_row["level"],
                    hp=index_row["hp"],
                    drops=view.drops,
                )
            )
        except Exception:
            log.exception("monster %s failed; skipping", mid)
        if len(batch) >= 50 or i == len(ids):
            store.upsert_monsters(batch)
            log.info("upserted %s/%s monsters", i, len(ids))
            batch = []

    # 3) wiki turn-ins (public page, no login)
    resp = requests.get(WIKI_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    quests = parse_repeatable_quests(resp.text)
    store.replace_turnins(quests, NPC_PURCHASABLE)
    resolved = store.resolve_turnin_item_ids()
    log.info("turn-ins: %s quests stored, %s item ids resolved", len(quests), resolved)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = load_settings()
    client = RoClient(s.session_cookie, s.throttle_seconds)
    client.ensure_authed()
    run(client, Store(s.database_url))


if __name__ == "__main__":
    main()
