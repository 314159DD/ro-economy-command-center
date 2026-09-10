"""the server's wiki documents custom NPC shop prices (Modified_Sales_Prices) —
the page that would have saved the player 50k on Khukris. Parse it and apply
the overrides on top of mainline Hercules sell prices."""
import pathlib

from ro_collector.parse_wiki import parse_modified_sales
from ro_collector.enrich_npcsell import apply_modified_sales

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "wiki_modified_sales.html"


def test_parses_real_wiki_page():
    rows = parse_modified_sales(FIXTURE.read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in rows}
    assert by_name["Khukri"] == {"name": "Khukri", "original": 120_000, "modified": 25_000}
    assert by_name["Green Salad"]["modified"] == 2_000
    assert len(rows) == 8


def test_apply_overrides_matches_by_name_and_original_price():
    prices = {13006: 120_000, 13007: 5_000, 748: 27_500}
    names = {13006: "Khukri", 13007: "Khukri", 748: "Witherless Rose"}  # name collision
    rows = [
        {"name": "Khukri", "original": 120_000, "modified": 25_000},
        {"name": "Witherless Rose", "original": 27_500, "modified": 7_500},
        {"name": "Unknown Thing", "original": 9, "modified": 5},
    ]
    unresolved = apply_modified_sales(prices, names, rows)
    assert prices[13006] == 25_000    # matched by name AND original price
    assert prices[13007] == 5_000     # different original -> untouched
    assert prices[748] == 7_500
    assert unresolved == ["Unknown Thing"]
