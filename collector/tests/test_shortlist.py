from ro_collector.models import Listing
from ro_collector.shortlist import build_report


def test_report_sections_and_ordering():
    listings = [Listing("M", "s", "prt_mk", 1, 1, 7003, "Anolian Skin", 0, "None", 100, 500)]
    buy_orders = [Listing("B", "s", "prt_mk", 2, 2, 607, "Yggdrasil Berry", 0, "None", 100, 200_000)]
    drops = [
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 7003, "item_name": "Anolian Skin", "rate": 100.0},
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 607, "item_name": "Yggdrasil Berry", "rate": 0.05},
    ]
    spots = [
        {"name": "Anolian River", "map": "cmd_fild01", "monster_ids": [1206], "min_level": 70,
         "kills_per_hour": 400, "arrows_per_hour": 2000, "arrow_price": 2, "calibrated": False,
         "notes": "Hunt combo: Cuir (137.9k base/50)"},
        {"name": "Endgame Spot", "map": "thor_v03", "monster_ids": [1206], "min_level": 90,
         "kills_per_hour": 500, "arrows_per_hour": 2000, "arrow_price": 2, "calibrated": False},
    ]
    report = build_report(listings, buy_orders, [], drops, spots, [], char_level=72)

    assert "## GRIND BOARD" in report
    assert "Anolian River" in report
    assert "estimated" in report          # confidence tag
    assert "note: Hunt combo: Cuir (137.9k base/50)" in report  # seed notes surfaced in report
    assert "## LOCKED SPOTS" in report
    assert "Endgame Spot" in report and "90" in report
    assert "## BUYER ORDERS" in report
    assert "Yggdrasil Berry" in report
    assert "20,000,000" in report         # 100 x 200k total demand
    assert "## EXP PLANNER" in report

    # Verify section ordering: GRIND BOARD < LOCKED SPOTS < BUYER ORDERS < EXP PLANNER
    grind_idx = report.index("## GRIND BOARD")
    locked_idx = report.index("## LOCKED SPOTS")
    buyer_idx = report.index("## BUYER ORDERS")
    exp_idx = report.index("## EXP PLANNER")
    assert grind_idx < locked_idx < buyer_idx < exp_idx


def test_grind_board_sorted_by_ev():
    listings = [Listing("M", "s", "m", 1, 1, 7003, "Skin", 0, "None", 10, 1000)]
    drops = [{"monster_id": 1, "monster_name": "A", "item_id": 7003, "item_name": "Skin", "rate": 100.0}]
    spots = [
        {"name": "Slow", "map": "m1", "monster_ids": [1], "min_level": 1,
         "kills_per_hour": 100, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False},
        {"name": "Fast", "map": "m2", "monster_ids": [1], "min_level": 1,
         "kills_per_hour": 500, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False},
    ]
    report = build_report(listings, [], [], drops, spots, [], char_level=72)
    assert report.index("Fast") < report.index("Slow")


def test_demand_only_item_counts_in_grind_board():
    """An item with a standing buy order but NO vendor listing must still be
    valued at the bid in the grind board — a buy order is a guaranteed sale,
    with or without vendor supply."""
    buy_orders = [Listing("B", "s", "prt_mk", 2, 2, 607, "Yggdrasil Berry", 0, "None", 100, 200_000)]
    drops = [
        # 2% is above the lottery rate cutoff -> counts as reliable income
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 607, "item_name": "Yggdrasil Berry", "rate": 2.0},
    ]
    spots = [
        {"name": "Anolian River", "map": "cmd_fild01", "monster_ids": [1206], "min_level": 70,
         "kills_per_hour": 400, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False},
    ]
    report = build_report([], buy_orders, [], drops, spots, [], char_level=72)
    # 2% x 200k x 400 kph = 1,600,000 z/hr, demand-backed
    assert "Yggdrasil Berry (1,600,000/hr) ✓" in report


def test_buyer_orders_aggregates_same_item():
    """Multiple buy orders for the same item at different prices: shows max price and aggregated qty/total."""
    buy_orders = [
        Listing("B", "s", "prt_mk", 1, 1, 501, "Teddybear Doll", 0, "None", 100, 200_000),  # 100 @ 200k
        Listing("B", "s", "prt_mk", 2, 2, 501, "Teddybear Doll", 0, "None", 50, 180_000),   # 50 @ 180k
    ]
    report = build_report([], buy_orders, [], [], [], [], char_level=1)

    # Should aggregate: 150 total qty, max price 200k, total zeny 100*200k + 50*180k = 29,000,000
    assert "150" in report  # total qty
    assert "200,000" in report  # max price
    assert "29,000,000" in report  # 100*200k + 50*180k
