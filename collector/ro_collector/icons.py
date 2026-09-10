"""Item icon cache: the server's CP serves ~300-byte item icons publicly (no auth,
no Cloudflare gate) at data/items/icons/<id>.png. Download each icon once
into a disk cache; the dashboard embeds them as data URIs so the HTML stays
a single self-contained offline file."""
import base64
import logging
import time
from pathlib import Path

import requests

from ro_collector.config import cp_url

log = logging.getLogger("ro.icons")

ICON_URL = cp_url() + "data/items/icons/{id}.png"
MOB_URL = cp_url() + "data/monsters/{id}.gif"
THROTTLE_SECONDS = 0.05
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_session = None  # keep-alive connection reuse: ~10x faster than per-request TLS


def _http_fetch(any_id: int, url_tpl: str = ICON_URL) -> bytes | None:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(_UA)
    try:
        r = _session.get(url_tpl.format(id=any_id), timeout=10)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.content:
        return None
    time.sleep(THROTTLE_SECONDS)
    return r.content


def _http_fetch_mob(mob_id: int) -> bytes | None:
    return _http_fetch(mob_id, MOB_URL)


def _ensure(ids, cache_dir, ext, fetch, label) -> None:
    """Download images missing from cache_dir. Failures are skipped (retried
    on the next build) so an offline rebuild still works with what's cached."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    missing = [i for i in sorted(set(ids)) if not (cache / f"{i}.{ext}").exists()]
    if not missing:
        return
    log.info("fetching %d %s", len(missing), label)
    got = 0
    for any_id in missing:
        data = fetch(any_id)
        if data:
            (cache / f"{any_id}.{ext}").write_bytes(data)
            got += 1
    log.info("%s: %d fetched, %d unavailable", label, got, len(missing) - got)


# The CP answers HTTP 200 with a generic "no sprite" image for monsters it has
# no art for (58 of 1007 mobs) — showing that is worse than showing nothing.
MOB_PLACEHOLDER_MD5 = "97ea4fb98f00604b5ee035dfd0c68513"


def _data_uris(ids, cache_dir, ext, mime, exclude_md5: str | None = None) -> dict[int, str]:
    import hashlib
    cache = Path(cache_dir)
    out: dict[int, str] = {}
    for any_id in set(ids):
        p = cache / f"{any_id}.{ext}"
        if not p.exists():
            continue
        data = p.read_bytes()
        if exclude_md5 and hashlib.md5(data).hexdigest() == exclude_md5:
            continue
        out[any_id] = f"data:{mime};base64," + base64.b64encode(data).decode()
    return out


def ensure_icons(item_ids, cache_dir, fetch=None) -> None:
    _ensure(item_ids, cache_dir, "png", fetch or _http_fetch, "item icons")


def icon_data_uris(item_ids, cache_dir) -> dict[int, str]:
    """item_id -> data URI for every requested icon present in the cache."""
    return _data_uris(item_ids, cache_dir, "png", "image/png")


def ensure_mob_icons(mob_ids, cache_dir, fetch=None) -> None:
    _ensure(mob_ids, cache_dir, "gif", fetch or _http_fetch_mob, "monster sprites")


def mob_icon_data_uris(mob_ids, cache_dir) -> dict[int, str]:
    """monster_id -> data URI for every cached sprite (placeholder art dropped)."""
    return _data_uris(mob_ids, cache_dir, "gif", "image/gif", exclude_md5=MOB_PLACEHOLDER_MD5)
