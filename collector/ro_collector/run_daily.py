"""Daily scrape: vendors + buyers -> snapshot -> diff vs previous complete snapshot."""
import logging

from .config import load_settings
from .db import Store
from .diff import diff_snapshots
from .http_client import RoClient
from .parse_merchant import parse_merchant_page, total_pages

log = logging.getLogger("ro.daily")


def scrape_kind(client, kind: str):
    first = parse_merchant_page(client.get_page(module="merchant", action=kind, p=1), kind)
    rows = list(first.rows)
    complete = True
    consecutive_failures = 0
    for p in range(2, total_pages(first.total_records) + 1):
        page = None
        for attempt in range(3):
            try:
                page = parse_merchant_page(client.get_page(module="merchant", action=kind, p=p), kind)
                break
            except Exception:
                if attempt == 2:
                    log.exception("page %s p=%s failed after 3 attempts; snapshot incomplete", kind, p)
                    complete = False
        if page is None:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                log.error("5 consecutive page failures — aborting remaining pages, snapshot incomplete")
                complete = False
                break
            continue
        consecutive_failures = 0
        if not page.rows:
            # An empty page means we have paginated past the last record. The
            # true page count drifts as listings churn, so total_pages() can
            # overshoot; stop cleanly here rather than flagging the snapshot bad.
            log.info("%s p=%s empty — end of data at %s rows", kind, p, len(rows))
            break
        rows.extend(page.rows)
    # A record-count regex miss (total_records == 0) or a large shortfall in
    # collected rows still marks the snapshot unreliable (guards against an
    # early break caused by a challenge/error page rather than the true end).
    complete = complete and first.total_records > 0 and len(rows) >= 0.9 * first.total_records
    return rows, first.total_records, complete


def run(client, store) -> None:
    for kind in ("vendors", "buyers"):
        rows, total, complete = scrape_kind(client, kind)
        snap_id = store.insert_snapshot(kind, total, complete, rows)
        log.info("%s snapshot %s: %s rows, complete=%s", kind, snap_id, len(rows), complete)

    ids = store.latest_complete_snapshot_ids("vendors", 2)
    if len(ids) == 2:
        curr_id, prev_id = ids
        if store.pair_already_diffed(prev_id, curr_id):
            log.info("pair %s->%s already diffed; skipping", prev_id, curr_id)
        else:
            sales = diff_snapshots(store.listings_for_snapshot(prev_id), store.listings_for_snapshot(curr_id))
            store.insert_probable_sales(sales, prev_id, curr_id)
            log.info("diff %s->%s: %s probable sales", prev_id, curr_id, len(sales))
    else:
        log.info("fewer than 2 complete vendor snapshots; diff skipped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = load_settings()
    client = RoClient(s.session_cookie, s.throttle_seconds)
    client.ensure_authed()
    run(client, Store(s.database_url))


if __name__ == "__main__":
    main()
