import os
import pathlib

import pytest

from ro_collector.db import Store
from ro_collector.models import Listing

TEST_DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


def test_snapshot_roundtrip():
    store = Store(TEST_DB)
    schema = (pathlib.Path(__file__).parents[1] / "schema.sql").read_text(encoding="utf-8")
    store.init_schema(schema)

    rows = [Listing("Don", "Shop", "prt_mk", 169, 226, 1030, "Tiger's Footskin", 0, "None", 1, 39_950_000)]
    snap_id = store.insert_snapshot("vendors", 1, True, rows)

    assert store.latest_complete_snapshot_ids("vendors", 1) == [snap_id]
    got = store.listings_for_snapshot(snap_id)
    assert got == rows
