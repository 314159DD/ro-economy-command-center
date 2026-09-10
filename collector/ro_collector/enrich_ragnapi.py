"""Enrich the monster table with RagnaAPI spawn + combat + EXP data.

RagnaAPI is public (no Cloudflare gate), so this runs headless anywhere. Fills
the gaps the server CP lacks: spawn maps/density (fix the seed's guessed maps),
flee/def/element (kill-speed + arrow choice), and per-kill base/job EXP. Run it
occasionally alongside refresh.bat -- monster data changes rarely.
"""
import logging

import requests

from .config import load_settings
from .db import Store
from .http_client import USER_AGENT
from .parse_ragnapi import parse_ragnapi_monster

log = logging.getLogger("ro.enrich")
API = "https://ragnapi.com/api/v1/old-times/monsters/{}"


def run(store: Store, throttle_seconds: float = 0.35) -> None:
    import time

    ids = store.monster_ids()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    done = miss = 0
    for i, mid in enumerate(ids, 1):
        try:
            r = session.get(API.format(mid), timeout=20)
            if r.status_code != 200:
                miss += 1
            else:
                meta, spawns = parse_ragnapi_monster(r.json())
                store.upsert_monster_meta(meta)
                store.replace_spawns(mid, spawns)
                done += 1
        except Exception:
            miss += 1
            log.exception("ragnapi %s failed; skipping", mid)
        if i % 100 == 0:
            log.info("enriched %s/%s (%s ok, %s missing)", i, len(ids), done, miss)
        time.sleep(throttle_seconds)
    log.info("done: %s enriched, %s missing of %s", done, miss, len(ids))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = load_settings()
    run(Store(s.database_url))


if __name__ == "__main__":
    main()
