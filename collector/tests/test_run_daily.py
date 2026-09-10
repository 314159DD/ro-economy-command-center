from ro_collector import run_daily
from ro_collector.models import Listing


def _row_html(page, i):
    return (
        f'<tr><td>M{page}-{i}</td><td>shop</td><td>prt_mk 10 20</td><td></td>'
        f'<td><a href="?module=item&action=view&id=1030">Item{page}-{i}</a></td>'
        f'<td>1</td><td>1,000 z</td><td>None</td></tr>'
    )


def _page_html(records, page, rows_per_page=20):
    """20 rows/page mirrors production (per_page=20), so completeness checks
    that compare row count against the advertised record total behave realistically."""
    trs = "".join(_row_html(page, i) for i in range(rows_per_page))
    return (
        f"<html><body><p>Total of {records} records</p>"
        f'<table class="horizontal-table"><tr><th>Merchant</th></tr>{trs}</table></body></html>'
    )


NO_COUNT_PAGE = """
<html><body><table class="horizontal-table"><tr><th>Merchant</th></tr>
<tr>
  <td>M1</td><td>shop</td><td>prt_mk 10 20</td><td></td>
  <td><a href="?module=item&action=view&id=1030">Item1</a></td>
  <td>1</td><td>1,000 z</td><td>None</td>
</tr></table></body></html>
"""


def _empty_page_html(records):
    """A valid FluxCP page paginated past the last record: no listing table."""
    return f"<html><body><p>Total of {records} records</p><div>No results.</div></body></html>"


class FakeClient:
    def __init__(self, fail_pages=(), total_records=40, empty_from=None):
        self.fail_pages = set(fail_pages)
        self.total_records = total_records
        self.empty_from = empty_from  # first page number that returns an empty (past-end) page
        self.calls = []

    def get_page(self, **params):
        p = params.get("p", 1)
        self.calls.append(p)
        if p in self.fail_pages:
            raise RuntimeError("boom")
        if self.empty_from is not None and p >= self.empty_from:
            return _empty_page_html(self.total_records)
        return _page_html(self.total_records, p)  # 40 records -> 2 pages of 20 rows


class NoRecordCountClient:
    """page-1 HTML has the listings table but no 'total of N records' text."""

    def __init__(self):
        self.calls = []

    def get_page(self, **params):
        self.calls.append(params.get("p", 1))
        return NO_COUNT_PAGE


class FakeStore:
    def __init__(self, ids=(), already_diffed=False, listings_by_id=None):
        self.snapshots = []
        self.sales = []
        self._ids = list(ids)
        self._already_diffed = already_diffed
        self._listings_by_id = listings_by_id or {}

    def insert_snapshot(self, kind, total_records, complete, rows):
        self.snapshots.append((kind, total_records, complete, rows))
        return len(self.snapshots)

    def latest_complete_snapshot_ids(self, kind, n=2):
        return self._ids  # first-ever run: no diff (default: no ids)

    def listings_for_snapshot(self, sid):
        return self._listings_by_id.get(sid, [])

    def pair_already_diffed(self, prev_id, curr_id):
        return self._already_diffed

    def insert_probable_sales(self, sales, prev_id, curr_id):
        self.sales.append((sales, prev_id, curr_id))


def test_scrape_all_pages_happy_path():
    client = FakeClient()
    rows, total, complete = run_daily.scrape_kind(client, "vendors")
    assert total == 40
    assert complete is True
    assert len(rows) == 40  # 20 rows/page, 2 pages
    assert client.calls == [1, 2]


def test_failed_page_marks_incomplete_after_retries():
    client = FakeClient(fail_pages={2})
    rows, total, complete = run_daily.scrape_kind(client, "vendors")
    assert complete is False
    assert len(rows) == 20  # only page 1 succeeded
    assert client.calls == [1, 2, 2, 2]  # page 2 retried 3x


def test_missing_record_count_forces_incomplete():
    """Regex miss on 'total of N records' -> total_records=0 -> complete must be False
    even though the single page parses cleanly (guards against a silently-lying complete flag)."""
    client = NoRecordCountClient()
    rows, total, complete = run_daily.scrape_kind(client, "vendors")
    assert total == 0
    assert complete is False
    assert len(rows) == 1


def test_empty_tail_page_ends_scrape_and_stays_complete():
    """total_pages() overshoots as listings churn, so the scrape runs into empty
    past-end pages. Those must end the loop cleanly and keep the snapshot complete
    (this is the bug that made the first live run's grind board come back empty)."""
    # Advertise 65 records -> total_pages=4. Real data is 3 full pages (60 rows);
    # page 4 is empty. 60 >= 0.9*65, so the snapshot is legitimately complete.
    client = FakeClient(total_records=65, empty_from=4)
    rows, total, complete = run_daily.scrape_kind(client, "vendors")
    assert len(rows) == 60
    assert complete is True
    assert client.calls == [1, 2, 3, 4]  # stopped at the first empty page, no retries


def test_early_empty_page_still_marks_incomplete():
    """An empty page far short of the advertised total (e.g. a challenge/error page
    masquerading as end-of-data) must NOT pass as complete."""
    client = FakeClient(total_records=400, empty_from=3)  # 20 pages advertised, data 'ends' at page 2
    rows, total, complete = run_daily.scrape_kind(client, "vendors")
    assert len(rows) == 40  # pages 1-2 only
    assert complete is False  # 40 << 0.9*400
    assert client.calls == [1, 2, 3]  # broke at first empty page


def test_five_consecutive_page_failures_aborts_remaining_pages():
    """Session expiry mid-run shouldn't burn hundreds of doomed requests: after 5
    consecutive fully-failed pages, scrape_kind should stop requesting further pages."""
    # 300 records / 20 per page = 15 pages, well past the 5-failure abort threshold.
    client = FakeClient(fail_pages=set(range(2, 7)), total_records=300)
    rows, total, complete = run_daily.scrape_kind(client, "vendors")
    assert complete is False
    assert max(client.calls) == 6  # never requested page 7+
    assert 7 not in client.calls
    # pages 2-6 each retried 3x, plus the single successful page-1 call
    assert client.calls == [1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6]


def test_run_inserts_both_kinds_and_skips_diff_without_history():
    client = FakeClient()
    store = FakeStore()
    run_daily.run(client, store)
    kinds = [s[0] for s in store.snapshots]
    assert kinds == ["vendors", "buyers"]
    assert store.sales == []  # no prior snapshot -> no diff


def test_run_skips_diff_when_pair_already_diffed():
    client = FakeClient()
    store = FakeStore(ids=[2, 1], already_diffed=True)
    run_daily.run(client, store)
    assert store.sales == []  # already-diffed pair -> no duplicate insert


def test_run_diffs_new_pair_with_correct_argument_order():
    client = FakeClient()
    prev_listing = Listing("M1", "shop", "prt_mk", 10, 20, 1030, "Item", 0, "None", 10, 1000)
    curr_listing = Listing("M1", "shop", "prt_mk", 10, 20, 1030, "Item", 0, "None", 3, 1000)
    store = FakeStore(
        ids=[2, 1],
        already_diffed=False,
        listings_by_id={1: [prev_listing], 2: [curr_listing]},
    )
    run_daily.run(client, store)
    assert len(store.sales) == 1
    sales, prev_id, curr_id = store.sales[0]
    assert (prev_id, curr_id) == (1, 2)
    assert len(sales) == 1
    assert sales[0].qty == 7  # prev(10) - curr(3); a swapped arg order would yield no sale
