import json

from ro_collector.models import Listing
from ro_collector.report import build_html

GENERATED_AT = "2026-07-06 12:00:00 UTC"


def _fixtures():
    listings = [
        Listing("M", "s", "prt_mk", 1, 1, 7003, "Anolian Skin", 0, "None", 100, 500),
        # cheap vendor ask on an item with a much higher standing buy order -> arbitrage (Flipping tab)
        Listing("M", "s", "prt_mk", 3, 3, 909, "Poring Card", 0, "None", 5, 1_000),
    ]
    buy_orders = [
        Listing("B", "s", "prt_mk", 2, 2, 607, "Yggdrasil Berry", 0, "None", 100, 200_000),
        Listing("B", "s", "prt_mk", 4, 4, 909, "Poring Card", 0, "None", 3, 50_000),
    ]
    drops = [
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 7003, "item_name": "Anolian Skin", "rate": 100.0},
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 607, "item_name": "Yggdrasil Berry", "rate": 0.05},
        # a card drop with a live buyer order -> Card Grinds tab
        {"monster_id": 1002, "monster_name": "Poring", "item_id": 909, "item_name": "Poring Card", "rate": 0.02},
    ]
    spots = [
        {
            "name": "Anolian River", "map": "cmd_fild01", "monster_ids": [1206], "min_level": 70,
            "kills_per_hour": 400, "arrows_per_hour": 2000, "arrow_price": 2, "calibrated": False,
            "notes": "Hunt combo: Cuir (137.9k base/50)",
        },
        {
            "name": "Endgame Spot", "map": "thor_v03", "monster_ids": [1206], "min_level": 90,
            "kills_per_hour": 500, "arrows_per_hour": 2000, "arrow_price": 2, "calibrated": False,
        },
    ]
    return listings, buy_orders, drops, spots


def _extract_data_blob(html: str) -> dict:
    """DATA is emitted as compact (no-newline) JSON on a single script line."""
    line = html.split("const DATA = ", 1)[1].split("\n", 1)[0]
    return json.loads(line.rstrip().rstrip(";"))


def test_build_html_basic_structure_and_labels():
    listings, buy_orders, drops, spots = _fixtures()
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)

    assert "<!DOCTYPE html>" in html or "<html" in html
    # two new tabs plus the three that carry over unchanged
    for label in ("Lotteries", "Flipping", "Grind Board", "Item Explorer", "EXP Planner"):
        assert label in html
    assert "Anolian River" in html  # known spot
    assert "Anolian Skin" in html  # known item
    assert "const DATA" in html  # embedded data blob


def test_build_html_embeds_valid_json_matching_shortlist_math():
    listings, buy_orders, drops, spots = _fixtures()
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    assert data["char_level"] == 72
    assert data["generated_at"] == GENERATED_AT

    grind_open = {s["spot"]: s for s in data["grind_open"]}
    assert "Anolian River" in grind_open
    assert "Endgame Spot" not in grind_open  # locked out at level 72 (min_level 90)

    grind_locked = {s["spot"]: s for s in data["grind_locked"]}
    assert grind_locked["Endgame Spot"]["min_level"] == 90

    items = {i["item_name"]: i for i in data["items"]}
    assert "Anolian Skin" in items
    assert "Yggdrasil Berry" in items
    assert items["Anolian Skin"]["vendor_low"] == 500

    # Lotteries: the Poring Card drop, backed by its buy order, ranked by value
    card_rows = {c["item"]: c for c in data["lotteries"]}
    assert "Poring Card" in card_rows
    assert card_rows["Poring Card"]["monster"] == "Poring"
    assert card_rows["Poring Card"]["backed"] is True
    assert card_rows["Poring Card"]["kind"] == "card"

    # Flipping: vendor ask (1,000) undercuts the standing buy order (50,000)
    flip_rows = {f["item"]: f for f in data["flips"]}
    assert "Poring Card" in flip_rows
    assert flip_rows["Poring Card"]["vendor_low"] == 1_000
    assert flip_rows["Poring Card"]["exit_price"] == 50_000
    assert flip_rows["Poring Card"]["exit"] == "buyer"
    assert flip_rows["Poring Card"]["total_profit"] == 49_000 * 3


def test_item_explorer_includes_drop_only_items_with_no_vendor_price():
    """An item only ever seen as a monster drop (never vendor-listed) must still
    surface in the Item Explorer, with vendor_low/supply as null (rendered '—')."""
    listings, buy_orders, drops, spots = _fixtures()
    drops = drops + [
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 9999, "item_name": "Rare Card", "rate": 0.01},
    ]
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    items = {i["item_name"]: i for i in data["items"]}
    assert "Rare Card" in items
    assert items["Rare Card"]["vendor_low"] is None
    assert items["Rare Card"]["best_drop_name"] == "Anolian"


def test_build_html_handles_empty_buyers_and_turnins():
    listings, _buy_orders, drops, spots = _fixtures()
    html = build_html(listings, [], [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    # no buy orders -> no demand backing, so no arbitrage and no card is demand-priced
    assert data["flips"] == []
    assert data["exp"] == []
    assert "Lotteries" in html
    assert "Flipping" in html
    assert "EXP Planner" in html


def test_flipping_tab_supports_npc_overcharge_exits():
    """Unified flips: buyer exits and NPC Overcharge exits in one table with a
    switcher; npc_sell prices flow through build_html."""
    listings, buy_orders, drops, spots = _fixtures()
    listings = listings + [
        Listing("OreGuy", "s", "geffen", 10, 10, 998, "Iron", 0, "None", 800, 40),
    ]
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      npc_sell={998: 50})
    data = _extract_data_blob(html)

    iron = {f["item"]: f for f in data["flips"]}["Iron"]
    assert iron["exit"] == "npc"
    assert iron["exit_price"] == 62
    assert iron["total_profit"] == (62 - 40) * 800
    assert 'id="flip-kind-filter"' in html   # All / Buyers / NPC switcher
    assert 'data-exit="npc"' in html


def test_view_polish_hero_toggles_snipes_tab_and_tab_order():
    """Hero cards are individually hideable (persisted), Undercut Snipes has
    its own tab, and Buyer Orders sits between Item Explorer and EXP Planner."""
    listings, buy_orders, drops, spots = _fixtures()
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    assert "hero-x" in html               # per-card hide control
    assert "ro_hero_hidden" in html     # persistence key
    assert 'data-tab="tab-snipes"' in html
    assert 'id="tab-snipes"' in html
    nav = html.split('<nav', 1)[1].split("</nav>", 1)[0]
    order = [t for t in ("Grind Board", "Lotteries", "Flipping", "Snipes",
                         "Item Explorer", "Buyer Orders", "EXP Planner")]
    positions = [nav.index(label) for label in order]
    assert positions == sorted(positions)


def test_snapshot_age_indicator():
    """Flips are perishable (the player bought into moved prices twice) - the page
    shows how old the snapshot is and colors it when stale."""
    listings, buy_orders, drops, spots = _fixtures()
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      generated_ts=1780000000)
    data = _extract_data_blob(html)
    assert data["generated_ts"] == 1780000000
    assert 'id="chip-age"' in html


def test_aero_redesign_ships_mode_toggle_and_hero():
    """Frutiger Aero redesign: day/night mode toggle (persisted) and the hero
    section (featured spot + stat tiles) ship in the page."""
    listings, buy_orders, drops, spots = _fixtures()
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    assert 'id="mode-toggle"' in html
    assert "ro_mode" in html          # persisted mode key
    assert 'id="hero"' in html
    assert 'data-mode' in html


def test_buyer_orders_has_its_own_tab_with_aggregated_demand():
    """Buyer Orders is a dedicated tab again (was folded into Item Explorer):
    one row per demanded item — best bid, total qty wanted, order count, total
    zeny on the table — plus vendor low and best drop source so you can decide
    farm vs flip. Sorted by total demand."""
    listings, buy_orders, drops, spots = _fixtures()
    buy_orders = buy_orders + [
        # second, lower Yggdrasil Berry order: aggregates with the 200k one
        Listing("B2", "s", "prt_mk", 6, 6, 607, "Yggdrasil Berry", 0, "None", 50, 180_000),
    ]
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    rows = {r["item_name"]: r for r in data["buyer_orders"]}
    ygg = rows["Yggdrasil Berry"]
    assert ygg["best_price"] == 200_000
    assert ygg["qty_wanted"] == 150
    assert ygg["orders"] == 2
    assert ygg["demand_total"] == 100 * 200_000 + 50 * 180_000
    assert ygg["best_drop_name"] == "Anolian"
    assert ygg["vendor_low"] is None  # never vendor-listed in fixtures

    poring = rows["Poring Card"]
    assert poring["vendor_low"] == 1_000

    # biggest demand first
    assert data["buyer_orders"][0]["item_name"] == "Yggdrasil Berry"

    # the tab ships in the page chrome alongside the existing five
    assert "Buyer Orders" in html
    assert 'id="tab-buyers"' in html
    for label in ("Grind Board", "Lotteries", "Flipping", "Item Explorer", "EXP Planner"):
        assert label in html


def test_grind_board_shows_level_hp_and_lottery_upside():
    """Grind Board rows carry the primary mob's Lvl/HP (like Card Grinds) and a
    single 'Lottery upside/hr' figure (summed card EV) instead of leaving the
    card_ev_per_hour math invisible."""
    listings, buy_orders, drops, spots = _fixtures()
    drops = drops + [
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 4234, "item_name": "Anolian Card", "rate": 0.01},
    ]
    buy_orders = buy_orders + [
        Listing("B", "s", "prt_mk", 7, 7, 4234, "Anolian Card", 0, "None", 1, 5_000_000),
    ]
    meta_by_id = {1206: {"boss_class": "normal", "level": 63, "hp": 18960, "base_exp": 900}}

    html = build_html(
        listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
        meta_by_id=meta_by_id,
    )
    data = _extract_data_blob(html)

    row = {s["spot"]: s for s in data["grind_open"]}["Anolian River"]
    assert row["level"] == 63
    assert row["hp"] == 18960
    # Anolian Card 0.01% * 5M * 400 kph = 200k/hr, plus the Yggdrasil Berry
    # (0.05% @ 200k = 40k/hr) which is rare+valuable enough to count as a
    # lottery too rather than reliable income.
    assert row["lottery_ev"] == 240_000
    assert "Lottery upside" in html


def test_dashboard_ships_kills_per_min_override_hooks():
    """The kills/min manual-override UI needs: monster_id + kph/kph_source on
    every lottery row, kph + arrow_cost on every grind row, and the JS hooks
    (editable cells + localStorage persistence) in the page."""
    listings, buy_orders, drops, spots = _fixtures()
    meta_by_id = {1002: {"boss_class": "normal", "hp": 50, "def": 0, "size": "small", "level": 1}}
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      meta_by_id=meta_by_id)
    data = _extract_data_blob(html)

    poring = {r["item"]: r for r in data["lotteries"]}["Poring Card"]
    assert poring["monster_id"] == 1002
    assert poring["kph"] > 0 and poring["kph_source"] == "model"  # not in any spot

    row = {s["spot"]: s for s in data["grind_open"]}["Anolian River"]
    assert row["kph"] == 400
    assert row["arrow_cost"] == 2000 * 2

    assert "kpm-edit" in html        # clickable cells
    assert "ro_kpm_v1" in html     # localStorage persistence key
    # the Grind Board has a dedicated, visible Kills/hr column for the entry
    assert '<th data-key="kph">' in html


def test_lotteries_shows_boss_class_spawn_info_and_farmable_toggle():
    """Lotteries must distinguish a farmable normal-mob card (green NORMAL,
    real spawn) from an MVP boss-hunt card (red MVP, single spawn), and must
    ship a 'Farmable only' filter control so the two are still both visible
    by default but filterable."""
    listings, buy_orders, drops, spots = _fixtures()
    drops = drops + [
        # a card from an MVP -- a boss hunt, not a normal grind
        {"monster_id": 1147, "monster_name": "Boss Test MVP", "item_id": 4001, "item_name": "Boss Card", "rate": 0.01},
    ]
    buy_orders = buy_orders + [
        Listing("B", "s", "prt_mk", 5, 5, 4001, "Boss Card", 0, "None", 1, 100_000),
    ]
    meta_by_id = {
        1002: {"boss_class": "normal", "level": 15, "hp": 10},
        1147: {"boss_class": "mvp", "level": 99, "hp": 500_000},
    }
    best_spawn_by_id = {
        1002: {"map_name": "prt_fild08", "amount": 50},
        1147: {"map_name": "prt_maze03", "amount": 1},
    }

    html = build_html(
        listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
        meta_by_id=meta_by_id, best_spawn_by_id=best_spawn_by_id,
    )
    data = _extract_data_blob(html)

    card_rows = {c["item"]: c for c in data["lotteries"]}
    assert card_rows["Poring Card"]["boss_class"] == "normal"
    assert card_rows["Poring Card"]["farmable"] is True
    assert card_rows["Poring Card"]["spawn_map"] == "prt_fild08"
    assert card_rows["Boss Card"]["boss_class"] == "mvp"
    assert card_rows["Boss Card"]["farmable"] is False
    assert card_rows["Boss Card"]["spawn_map"] == "prt_maze03"

    # rendered/labeled type badges present (either as data or client-render JS)
    assert "MVP" in html
    assert "NORMAL" in html

    # the farmable filter control ships with the tab
    assert 'id="card-farmable-toggle"' in html
    assert "Farmable only" in html

    # all five tabs still present
    for label in ("Grind Board", "Lotteries", "Flipping", "Item Explorer", "EXP Planner"):
        assert label in html


def test_dashboard_ships_icons_and_ro_tooltip():
    """Item rows render an icon (from DATA.icons data-URIs) and hover shows an
    RO-style tooltip driven by the per-item info map."""
    listings, buy_orders, drops, spots = _fixtures()
    icons = {7003: "data:image/png;base64,iVBORw0KGgo="}
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      icons=icons)
    data = _extract_data_blob(html)

    assert data["icons"]["7003"].startswith("data:image/png;base64,") or \
        data["icons"][7003].startswith("data:image/png;base64,")
    assert 'id="item-tooltip"' in html   # shared tooltip element
    assert "item-cell" in html           # hoverable item name cells
    assert "tt-id" in html               # item ID footer (for in-game commands)


def test_item_explorer_ships_price_history_and_signals_frame():
    """Clicking an Item Explorer row opens a detail panel: price chart (vendor
    low + buyer bid over snapshots) plus the market-signals frame (realized
    sales now; sell-through & flip prediction framed as 'collecting — day X')."""
    listings, buy_orders, drops, spots = _fixtures()
    history = {7003: [["2026-07-05", 480, None], ["2026-07-06", 500, 450]]}
    sales = [
        {"item_id": 7003, "refine": 0, "cards": "None", "price": 490, "qty": 3},
    ]
    html = build_html(listings, buy_orders, sales, drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      history=history)
    data = _extract_data_blob(html)

    assert data["history"]["7003"] == [["2026-07-05", 480, None], ["2026-07-06", 500, 450]]
    assert data["history_days"] == 2
    assert data["sales7"]["7003"]["n"] == 3          # qty sold in the window
    assert data["sales7"]["7003"]["med"] == 490
    # the detail-panel machinery ships in the page
    assert "item-detail" in html
    assert "drawChart" in html
    assert 'id="chart-tip"' in html


def test_flipping_tab_lists_undercut_snipes():
    """The impatient-seller case ships as a second table on the Flipping tab,
    with where-to-buy so the snipe is actionable."""
    listings, buy_orders, drops, spots = _fixtures()
    listings = listings + [
        Listing("Sky Sage Shop", "s", "morocc", 171, 52, 9024, "Costume Hat", 0, "None", 1, 2_000_000),
        Listing("Traiders", "s", "prt_mk", 166, 211, 9024, "Costume Hat", 0, "None", 1, 9_999_999),
        Listing("Traiders2", "s", "prt_mk", 166, 211, 9024, "Costume Hat", 0, "None", 1, 9_999_999),
    ]
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    rows = {r["item"]: r for r in data["undercuts"]}
    hat = rows["Costume Hat"]
    assert hat["price"] == 2_000_000
    assert hat["next_price"] == 9_999_999
    assert hat["where"] == "morocc (171,52)"
    assert 'id="uc-body"' in html
    assert "Undercut" in html


def test_grind_board_and_lotteries_show_monster_icons():
    """Grind rows carry the primary mob's monster_id; mob sprites are embedded
    (only the ones actually referenced) and rendered small in the rows."""
    listings, buy_orders, drops, spots = _fixtures()
    mob_icons = {1206: "data:image/gif;base64,R0lGOD=", 1002: "data:image/gif;base64,R0lGOD=",
                 9999: "data:image/gif;base64,unused"}
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      mob_icons=mob_icons)
    data = _extract_data_blob(html)

    row = {s["spot"]: s for s in data["grind_open"]}["Anolian River"]
    assert row["monster_id"] == 1206
    assert set(data["mob_icons"]) <= {"1206", "1002"}  # only referenced mobs embedded
    assert "9999" not in data["mob_icons"]
    assert "mob-ic" in html  # sprite render hook


def test_item_descriptions_flow_into_explorer_rows():
    """Descriptions from the game client's itemInfo ride along on the item
    rows so the hover tooltip can show the in-game effect text."""
    listings, buy_orders, drops, spots = _fixtures()
    item_info = {7003: {"description": "The scaled skin of an Anolian.", "item_type": "Etc",
                        "weight": 10, "atk": None, "defense": None, "slots": None, "equip_level": None}}
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      item_info=item_info)
    data = _extract_data_blob(html)

    row = {i["item_name"]: i for i in data["items"]}["Anolian Skin"]
    assert row["desc"] == "The scaled skin of an Anolian."
    assert row["item_type"] == "Etc"
    assert row["weight"] == 10


def test_lotteries_has_search_box():
    """571 lottery rows need a search field (filters by item OR source monster
    name, so 'yao' finds Yao Jun Card)."""
    listings, buy_orders, drops, spots = _fixtures()
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    assert 'id="lot-search"' in html


def test_lotteries_includes_rare_gear_with_kind_switcher():
    """The Orc Archer Bow case end-to-end: rare valuable equipment shows up in
    the Lotteries tab tagged GEAR (with vendor supply), and the tab ships an
    All / Cards / Gear view switcher."""
    listings, buy_orders, drops, spots = _fixtures()
    listings = listings + [
        Listing("M", "s", "prt_mk", 8, 8, 1734, "Orc Archer Bow", 0, "None", 1, 7_000_000),
    ]
    drops = drops + [
        {"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 1734, "item_name": "Orc Archer Bow", "rate": 0.1},
    ]
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    rows = {r["item"]: r for r in data["lotteries"]}
    bow = rows["Orc Archer Bow"]
    assert bow["kind"] == "gear"
    assert bow["value"] == 7_000_000
    assert bow["supply"] == 1
    assert bow["kills_to_first"] == 1000
    assert rows["Poring Card"]["kind"] == "card"

    # the All / Cards / Gear switcher ships with the tab
    assert 'id="lot-kind-filter"' in html
    assert 'data-kind="card"' in html
    assert 'data-kind="gear"' in html


def test_settings_plumbing_ships():
    listings, buy_orders, drops, spots = _fixtures()
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    assert 'id="settings-btn"' in html
    assert 'id="capital-input"' in html
    assert "ro_settings_v1" in html
    assert "wl-star" in html


def test_buyer_orders_farm_to_order():
    """Every buy order with a farmable source gets model-driven farm z/hr."""
    listings, buy_orders, drops, spots = _fixtures()
    meta_by_id = {1206: {"boss_class": "normal", "hp": 18960, "def": 15, "size": "large", "level": 61}}
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      meta_by_id=meta_by_id)
    data = _extract_data_blob(html)
    ygg = {r["item_name"]: r for r in data["buyer_orders"]}["Yggdrasil Berry"]
    assert ygg["monster_id"] == 1206
    assert ygg["kph"] > 0
    assert ygg["farm_zhr"] == round(0.05 / 100 * 200_000 * ygg["kph"])
    assert ygg["hours_to_fill"] == round(100 / (0.05 / 100 * ygg["kph"]), 1)
    assert '<th data-key="farm_zhr">' in html


def test_grind_board_gains_discovered_spots_for_all_farmable_mobs():
    """The Discovered spots panel ranks EVERY farmable mob by model z/hr, not
    just the 16 curated spots. Monster 1002 (Poring) isn't in any curated
    spot's monster_ids, so it's a discovery candidate once it has meta + a
    dense-enough spawn and a non-card drop worth something."""
    listings, buy_orders, drops, spots = _fixtures()
    listings = listings + [
        Listing("M", "s", "prt_fild08", 1, 1, 512, "Apple", 0, "None", 100, 5_000),
    ]
    drops = drops + [
        {"monster_id": 1002, "monster_name": "Poring", "item_id": 512, "item_name": "Apple", "rate": 100.0},
    ]
    meta_by_id = {1002: {"boss_class": "normal", "hp": 50, "def": 0, "size": "small", "level": 1, "base_exp": 10}}
    best_spawn_by_id = {1002: {"map_name": "prt_fild08", "amount": 60}}
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      meta_by_id=meta_by_id, best_spawn_by_id=best_spawn_by_id)
    data = _extract_data_blob(html)

    poring = next(r for r in data["discovered"] if r["monster_id"] == 1002)
    assert poring["kph"] > 0
    assert poring["zhr"] > 0
    assert 'id="disc-body"' in html


def test_market_maker_tab_ships_with_velocity_spread_rows():
    """Market Maker: items proven to sell (>=3 sales, velocity) currently
    listed below their realized price -- buy cheap, vend at realized."""
    listings, buy_orders, drops, spots = _fixtures()
    sales = [
        {"item_id": 7003, "refine": 0, "cards": "None", "price": 600, "qty": 3},
        {"item_id": 7003, "refine": 0, "cards": "None", "price": 600, "qty": 3},
        {"item_id": 7003, "refine": 0, "cards": "None", "price": 600, "qty": 3},
    ]
    html = build_html(listings, buy_orders, sales, drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    rows = {r["item"]: r for r in data["mm"]}
    assert "Anolian Skin" in rows
    assert rows["Anolian Skin"]["profit_day"] > 0
    assert 'id="mm-body"' in html

    nav = html.split('<nav', 1)[1].split("</nav>", 1)[0]
    order = ("Grind Board", "Lotteries", "Flipping", "Snipes", "Market Maker", "Item Explorer")
    positions = [nav.index(label) for label in order]
    assert positions == sorted(positions)


def test_corners_tab_ships_buyable_monopolies():
    """Corners: few sellers + proven demand + affordable total supply -> buy
    it all, relist higher. Capital-filtered client-side (gear icon setting)."""
    listings, buy_orders, drops, spots = _fixtures()
    listings = listings + [
        # a second, smaller seller on the same comparable item -> 2 sellers total
        Listing("B2", "s", "gef", 5, 5, 7003, "Anolian Skin", 0, "None", 20, 480),
    ]
    sales = [{"item_id": 7003, "refine": 0, "cards": "None", "price": 600, "qty": 5} for _ in range(3)]
    html = build_html(listings, buy_orders, sales, drops, spots, [], char_level=72, generated_at=GENERATED_AT)
    data = _extract_data_blob(html)

    assert len(data["corners"]) >= 1
    r = data["corners"][0]
    assert r["sellers"] == 2
    assert r["qty"] > 0
    assert r["cost"] > 0
    assert r["relist"] > 0
    assert r["payoff"] > 0

    assert 'id="corner-body"' in html
    assert "check server rules" in html

    nav = html.split('<nav', 1)[1].split("</nav>", 1)[0]
    order = ("Market Maker", "Corners", "Item Explorer")
    positions = [nav.index(label) for label in order]
    assert positions == sorted(positions)


def test_merchants_tab_ships_habitual_undercutter_directory():
    """Merchants: sellers who repeatedly list below realized value across
    recent snapshots -- a standing snipe subscription, not a one-off deal."""
    listings, buy_orders, drops, spots = _fixtures()
    sales = [{"item_id": 909, "refine": 0, "cards": "None", "price": 100, "qty": 1} for _ in range(3)]
    merchant_history = [
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 60, "amount": 10, "d": "2026-07-05"},
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 70, "amount": 5, "d": "2026-07-06"},
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 60, "amount": 10, "d": "2026-07-04"},
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 60, "amount": 10, "d": "2026-07-04"},
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 999, "amount": 1, "d": "2026-07-06"},
    ]
    html = build_html(listings, buy_orders, sales, drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      merchant_history=merchant_history)
    data = _extract_data_blob(html)

    assert data["merchants"][0]["merchant"] == "CheapBot"
    assert 'id="merch-body"' in html

    nav = html.split('<nav', 1)[1].split("</nav>", 1)[0]
    order = ("Buyer Orders", "Merchants", "EXP Planner")
    positions = [nav.index(label) for label in order]
    assert positions == sorted(positions)


def test_trade_ledger_pnl_and_goal_bar_ship():
    """Task 8: strategy P&L and logged balances flow into the data blob, and
    the 1B-zeny progress bar ships in the page chrome (the digest panel was
    removed on request 2026-07-07)."""
    listings, buy_orders, drops, spots = _fixtures()
    pnl = {"mm": {"realized": 650, "open_qty": 5, "open_cost": 600}}
    balances = [["2026-07-06 20:00", 12_000_000]]
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      pnl=pnl, balances=balances)
    data = _extract_data_blob(html)

    assert data["pnl"]["mm"]["realized"] == 650
    assert data["balances"][0][1] == 12000000
    assert 'id="goal-bar"' in html
    assert 'id="digest"' not in html


def test_war_chest_ships_supplies_and_schedule():
    """War Chest v1: WoE countdown + war-supplies watchboard. Rows come from
    a curated item-id seed list (war_items) scored against the same stats/
    history plumbing as the rest of the dashboard; the WoE schedule is a
    straight pass-through consumed by the client-side countdown."""
    listings, buy_orders, drops, spots = _fixtures()
    war_items = [{"item_id": 7003, "name": "Anolian Skin"}]
    history = {7003: [["2026-07-05", 520, None], ["2026-07-06", 500, None]]}
    woe = [{"weekday": 6, "start_hh": 16, "start_mm": 0, "duration_min": 60}]
    html = build_html(listings, buy_orders, [], drops, spots, [], char_level=72, generated_at=GENERATED_AT,
                      history=history, war_items=war_items, woe=woe)
    data = _extract_data_blob(html)

    assert data["war"][0]["low"] == 500
    assert data["war"][0]["delta7_pct"] == -3.8
    assert data["woe"][0]["weekday"] == 6
    assert 'id="war-body"' in html and 'id="woe-count"' in html

    nav = html.split('<nav', 1)[1].split("</nav>", 1)[0]
    order = ("Merchants", "War Chest", "EXP Planner")
    positions = [nav.index(label) for label in order]
    assert positions == sorted(positions)
