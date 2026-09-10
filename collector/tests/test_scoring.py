from ro_collector.models import Listing
from ro_collector.scoring import (
    demand_map, exp_per_zeny, flips, item_value, liquidity_factor,
    lottery_grinds, market_stats, spot_ev,
)


def test_lottery_grinds_ranks_by_value_with_source_and_time():
    drops = [
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 4234, "item_name": "Anolian Card", "rate": 0.05},
        {"monster_id": 1386, "monster_name": "Sleeper", "item_id": 4318, "item_name": "Sleeper Card", "rate": 0.05},
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 7003, "item_name": "Anolian Skin", "rate": 100.0},  # common drop
    ]
    markets = market_stats([L(item_id=4234, name="Anolian Card", price=5_000_000)], [], 7)
    demand = {4318: 236_020}  # Sleeper Card has a live buy order
    spots = [{"name": "Anolians", "monster_ids": [1206], "kills_per_hour": 900}]
    meta = {1206: {"boss_class": "normal", "level": 61, "hp": 18960},
            1386: {"boss_class": "mvp", "level": 99, "hp": 500000}}
    spawns = {1206: {"map_name": "clock_tower_bf", "amount": 120},
              1386: {"map_name": "boss_room", "amount": 1}}
    rows = lottery_grinds(drops, markets, demand, spots, meta, spawns)
    names = [r["item"] for r in rows]
    assert "Anolian Skin" not in names  # common high-rate drop is not a lottery
    anolian = next(r for r in rows if r["item"] == "Anolian Card")
    assert anolian["value"] == 5_000_000        # vendor low (no buy order)
    assert anolian["kind"] == "card"
    assert anolian["kills_to_first"] == 2000
    assert anolian["hours_to_first"] == round(2000 / 900, 1)
    assert anolian["boss_class"] == "normal" and anolian["level"] == 61 and anolian["farmable"] is True
    sleeper = next(r for r in rows if r["item"] == "Sleeper Card")
    assert sleeper["backed"] is True             # demand-backed
    assert sleeper["boss_class"] == "mvp" and sleeper["farmable"] is False  # single-spawn MVP
    assert rows[0]["value"] >= rows[-1]["value"]  # sorted desc


def test_lottery_grinds_includes_rare_valuable_gear():
    """The Orc Archer Bow case: a 7M-zeny equipment drop at 0.1% is the same
    shape of opportunity as a card grind and must surface, tagged 'gear',
    with vendor supply so market saturation is visible."""
    drops = [
        {"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 1734, "item_name": "Orc Archer Bow", "rate": 0.1},
        # valuable but high-rate: reliable income, not a lottery
        {"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 7203, "item_name": "Stem", "rate": 5.0},
    ]
    markets = market_stats(
        [L(item_id=1734, name="Orc Archer Bow", price=7_000_000, amount=1)] * 35
        + [L(item_id=7203, name="Stem", price=200_000)],
        [], 7)
    rows = lottery_grinds(drops, markets, {}, [], {1189: {"boss_class": "normal"}},
                          {1189: {"map_name": "gef_fild10", "amount": 60}})
    names = [r["item"] for r in rows]
    assert "Stem" not in names                   # 5% rate = reliable, not lottery
    bow = next(r for r in rows if r["item"] == "Orc Archer Bow")
    assert bow["kind"] == "gear"
    assert bow["value"] == 7_000_000
    assert bow["kills_to_first"] == 1000         # 1 / 0.1%
    assert bow["supply"] == 35                   # 35 vendors sitting on it
    assert bow["farmable"] is True


def test_lottery_grinds_qualifies_per_drop_not_per_item():
    """The real Orc Archer Bow case: it drops at 7.5% from Treasure Chest (MVP
    loot, not grindable) AND at 0.1% from Orc Archer. The high-rate non-lottery
    source must not disqualify the item — the 0.1% grind is still the jackpot,
    and the row must point at the best QUALIFYING source."""
    drops = [
        {"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 1734, "item_name": "Orc Archer Bow", "rate": 0.1},
        {"monster_id": 1324, "monster_name": "Treasure Chest", "item_id": 1734, "item_name": "Orc Archer Bow", "rate": 7.5},
    ]
    markets = market_stats([L(item_id=1734, name="Orc Archer Bow", price=7_000_000, amount=1)], [], 7)
    rows = lottery_grinds(drops, markets, {}, [], {1189: {"boss_class": "normal"}},
                          {1189: {"map_name": "gef_fild10", "amount": 60}})
    assert len(rows) == 1
    bow = rows[0]
    assert bow["item"] == "Orc Archer Bow"
    assert bow["monster"] == "Orc Archer"      # the grindable source, not the chest
    assert bow["rate"] == 0.1
    assert bow["kills_to_first"] == 1000


def test_lottery_and_flip_rows_carry_item_id():
    """The dashboard's icon + tooltip lookups key on item_id."""
    drops = [{"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 1734, "item_name": "Orc Archer Bow", "rate": 0.1}]
    markets = market_stats([L(item_id=1734, name="Orc Archer Bow", price=7_000_000, amount=1)], [], 7)
    rows = lottery_grinds(drops, markets, {}, [], {}, {})
    assert rows[0]["item_id"] == 1734

    listings = [L(item_id=909, name="Jellopy", price=100, amount=50)]
    buy_orders = [L(item_id=909, name="Jellopy", price=150, amount=30)]
    frows = flips(listings, buy_orders, market_stats(listings, [], 7))
    assert frows[0]["item_id"] == 909


def test_lottery_grinds_excludes_cheap_rare_drops():
    drops = [
        {"monster_id": 1002, "monster_name": "Poring", "item_id": 909, "item_name": "Jellopy Hat", "rate": 0.1},
    ]
    markets = market_stats([L(item_id=909, name="Jellopy Hat", price=5_000)], [], 7)
    assert lottery_grinds(drops, markets, {}, [], {}, {}) == []  # rare but worthless


def test_discover_spots_ranks_all_farmable_mobs():
    from ro_collector.scoring import discover_spots
    drops = [
        {"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 7203, "item_name": "Stem", "rate": 40.0},
        {"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 1734, "item_name": "Orc Archer Bow", "rate": 0.1},  # lottery, excluded
        {"monster_id": 1147, "monster_name": "Boss", "item_id": 7203, "item_name": "Stem", "rate": 90.0},  # mvp, excluded
    ]
    values = {7203: 5_000, 1734: 7_000_000}
    meta = {1189: {"boss_class": "normal", "hp": 1729, "def": 9, "size": "medium", "level": 49, "base_exp": 351},
            1147: {"boss_class": "mvp", "hp": 500_000, "def": 30, "size": "large", "level": 99, "base_exp": 99999}}
    spawns = {1189: {"map_name": "gef_fild10", "amount": 60}, 1147: {"map_name": "x", "amount": 1}}
    rows = discover_spots(drops, values, set(), meta, spawns, exclude_monster_ids=set(), char_level=99)
    assert len(rows) == 1
    r = rows[0]
    assert r["monster_id"] == 1189 and r["map"] == "gef_fild10"
    kph = r["kph"]
    assert r["zhr"] == round(0.40 * 5_000 * kph * 1.0)      # density 60 -> factor 1.0
    assert all(d["name"] != "Orc Archer Bow" for d in r["top_drops"])


def test_discover_spots_respects_exclusions_and_density():
    from ro_collector.scoring import discover_spots
    drops = [{"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 7203, "item_name": "Stem", "rate": 40.0}]
    values = {7203: 5_000}
    meta = {1189: {"boss_class": "normal", "hp": 1729, "def": 9, "size": "medium", "level": 49}}
    spawns = {1189: {"map_name": "gef_fild10", "amount": 10}}  # below 15 -> excluded
    assert discover_spots(drops, values, set(), meta, spawns, set(), 99) == []
    spawns = {1189: {"map_name": "gef_fild10", "amount": 60}}
    assert discover_spots(drops, values, set(), meta, spawns, {1189}, 99) == []  # curated exclusion


def test_undercuts_finds_impatient_seller():
    """The player's item-9024 case: one vendor at 2M while two others ask ~10M.
    Buying the cheap one and relisting near the higher asks is an opportunity.
    Requires >=2 other sellers so the reference price isn't one guy's dream."""
    from ro_collector.scoring import undercuts
    listings = [
        Listing("Sky Sage Shop", "Sky Sage Shop", "morocc", 171, 52, 9024, "Costume Hat", 0, "None", 1, 2_000_000),
        Listing("Traiders", "Thy For Buy", "prt_mk", 166, 211, 9024, "Costume Hat", 0, "None", 1, 9_999_999),
        Listing("Traiders", "Thy For Buy", "prt_mk", 166, 211, 9024, "Costume Hat", 0, "None", 1, 9_999_999),
    ]
    rows = undercuts(listings)
    assert len(rows) == 1
    r = rows[0]
    assert r["item_id"] == 9024
    assert r["price"] == 2_000_000 and r["qty"] == 1
    assert r["next_price"] == 9_999_999
    assert r["spread"] == 7_999_999
    assert r["potential"] == 7_999_999
    assert r["sellers_above"] == 2
    assert r["where"] == "morocc (171,52)"


def test_undercuts_needs_reference_depth_and_real_spread():
    from ro_collector.scoring import undercuts
    # only 2 listings -> the higher one is a single seller's wish, skip
    two = [
        Listing("A", "s", "m", 1, 1, 909, "Jellopy", 0, "None", 1, 100_000),
        Listing("B", "s", "m", 1, 1, 909, "Jellopy", 0, "None", 1, 1_000_000),
    ]
    assert undercuts(two) == []
    # small relative discount (80% of next ask) -> normal price competition, skip
    tight = [
        Listing("A", "s", "m", 1, 1, 909, "Jellopy", 0, "None", 1, 800_000),
        Listing("B", "s", "m", 1, 1, 909, "Jellopy", 0, "None", 1, 1_000_000),
        Listing("C", "s", "m", 1, 1, 909, "Jellopy", 0, "None", 1, 1_000_000),
    ]
    assert undercuts(tight) == []
    # refined/carded listings are not comparable -> never flagged against each other
    carded = [
        Listing("A", "s", "m", 1, 1, 1501, "Club", 7, "None", 1, 100_000),
        Listing("B", "s", "m", 1, 1, 1501, "Club", 0, "Fabre Card", 1, 900_000),
        Listing("C", "s", "m", 1, 1, 1501, "Club", 0, "None", 1, 900_000),
    ]
    assert undercuts(carded) == []


def test_flips_finds_buy_above_ask():
    listings = [L(item_id=909, name="Jellopy", price=100, amount=50)]  # vendor ask 100, stock 50
    buy_orders = [L(item_id=909, name="Jellopy", price=150, amount=30)]  # buyer pays 150, wants 30
    markets = market_stats(listings, [], 7)
    rows = flips(listings, buy_orders, markets)
    assert len(rows) == 1
    r = rows[0]
    assert r["exit"] == "buyer"
    assert r["vendor_low"] == 100 and r["exit_price"] == 150
    assert r["profit_per"] == 50
    assert r["qty"] == 30                 # min(stock 50, wanted 30)
    assert r["total_profit"] == 50 * 30
    assert r["where"] == "prt_mk (1,1)"   # where to buy


def test_flips_finds_npc_overcharge_exits():
    """The player's merchant has Overcharge +24%: any listing below
    floor(npc_sell x 1.24) is guaranteed profit with unlimited NPC liquidity.
    ALL qualifying listings count, not just the cheapest."""
    from ro_collector.scoring import OVERCHARGE_RATE
    assert OVERCHARGE_RATE == 1.24
    listings = [
        # Iron: npc_sell 50 -> OC exit 62. Two vendors below, one above.
        L(item_id=998, name="Iron", price=40, amount=500),
        L(item_id=998, name="Iron", price=55, amount=1000),
        L(item_id=998, name="Iron", price=70, amount=999),
    ]
    markets = market_stats(listings, [], 7)
    rows = flips(listings, [], markets, npc_sell={998: 50})
    assert len(rows) == 1
    r = rows[0]
    assert r["exit"] == "npc"
    assert r["exit_price"] == 62                       # floor(50 * 1.24)
    assert r["qty"] == 1500                            # both qualifying stacks
    assert r["cost"] == 40 * 500 + 55 * 1000
    assert r["total_profit"] == (62 - 40) * 500 + (62 - 55) * 1000
    assert r["vendor_low"] == 40


def test_npc_flips_skip_pocket_change():
    listings = [L(item_id=909, name="Jellopy", price=1, amount=100)]  # 2z exit, 100 profit total
    rows = flips(listings, [], market_stats(listings, [], 7), npc_sell={909: 2})
    assert rows == []  # below the worth-the-walk floor


def test_kills_from_loot_uses_highest_rate_drop():
    from ro_collector.scoring import kills_from_loot
    drops = [
        {"item_name": "Great Nature", "rate": 5.0},   # low rate, noisy
        {"item_name": "Fine Sand", "rate": 50.0},     # highest rate -> use this
    ]
    # 300 Fine Sand at 50% -> ~600 kills (preferred over Great Nature's estimate)
    assert kills_from_loot({"Great Nature": 20, "Fine Sand": 300}, drops) == 600
    assert kills_from_loot({"Unknown Item": 5}, drops) is None


def test_flips_ignores_non_arbitrage():
    listings = [L(item_id=909, price=200, amount=50)]   # ask 200
    buy_orders = [L(item_id=909, price=150, amount=30)]  # bid 150 < ask -> no flip
    rows = flips(listings, buy_orders, market_stats(listings, [], 7))
    assert rows == []


def L(item_id=909, name="Jellopy", refine=0, cards="None", amount=100, price=10):
    return Listing("M", "s", "prt_mk", 1, 1, item_id, name, refine, cards, amount, price)


def test_demand_map_takes_highest_buyer_price_per_item():
    orders = [L(item_id=7003, price=1000), L(item_id=7003, price=1420), L(item_id=501, price=40)]
    assert demand_map(orders) == {7003: 1420, 501: 40}


def test_item_value_demand_backed_uses_guaranteed_buyer_price():
    # A live buy order proves the item sells; use that price, no liquidity discount.
    stats = market_stats([L(item_id=7003, price=33333)], sales=[], window_days=7)[7003]
    assert item_value(stats, demand_price=1420) == 1420


def test_item_value_vendor_only_coldstart_is_heavily_discounted():
    # Club[3] case: 33k vendor ask, no buyer, no sales -> unproven -> low * 0.1.
    stats = market_stats([L(item_id=1501, price=33333)], sales=[], window_days=7)[1501]
    assert item_value(stats, demand_price=None) == 3333


def test_spot_ev_enrichment_exp_map_arrow():
    spot = {"name": "S", "map": "seed_map", "monster_ids": [1386], "min_level": 1,
            "kills_per_hour": 400, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False}
    drops = {1386: [{"item_id": 7099, "item_name": "Great Nature", "rate": 100.0}]}
    values = {7099: 3000}
    meta = {1386: {"base_exp": 3603, "best_element": "fire"}}
    spawns = {1386: {"map_name": "juno_field", "amount": 70}}
    ev = spot_ev(spot, drops, values, demand_ids=set(), meta_by_id=meta, best_spawn_by_id=spawns)
    assert ev.exp_per_hour == 3603 * 400        # base_exp x kills/hr
    assert ev.best_map == "juno_field"
    assert ev.density == 70
    assert ev.arrow == "fire"


def test_spot_ev_without_enrichment_defaults_blank():
    spot = {"name": "S", "map": "m", "monster_ids": [1], "min_level": 1,
            "kills_per_hour": 100, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False}
    ev = spot_ev(spot, {}, {})
    assert ev.exp_per_hour == 0 and ev.best_map == "" and ev.arrow == ""


def test_spot_ev_tags_demand_backed_drops():
    spot = {"name": "S", "map": "m", "monster_ids": [1], "min_level": 1,
            "kills_per_hour": 100, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False}
    drops = {1: [
        {"item_id": 7003, "item_name": "Anolian Skin", "rate": 100.0},
        {"item_id": 1501, "item_name": "Club", "rate": 100.0},
    ]}
    values = {7003: 1420, 1501: 3333}
    ev = spot_ev(spot, drops, values, demand_ids={7003})
    backed = {name: is_backed for name, _z, is_backed in ev.top_drops}
    assert backed["Anolian Skin"] is True
    assert backed["Club"] is False


def test_market_stats_comparable_filter_and_median():
    listings = [
        L(price=100), L(price=300), L(price=200),
        L(price=5000, refine=7),          # excluded: refined
        L(price=4000, cards="Fabre Card"),  # excluded: carded
    ]
    stats = market_stats(listings, sales=[], window_days=7)[909]
    assert stats.low == 100
    assert stats.median == 200
    assert stats.supply == 300  # 3 comparable listings x amount 100


def test_liquidity_factor_bounds():
    assert liquidity_factor(None) == 0.5
    assert liquidity_factor(0.0) == 0.2
    assert liquidity_factor(0.5) == 0.5
    assert liquidity_factor(3.0) == 1.0


def test_item_value_prefers_realized_price():
    sales = [
        {"item_id": 909, "refine": 0, "cards": "None", "price": 150, "qty": 2},
        {"item_id": 909, "refine": 0, "cards": "None", "price": 160, "qty": 1},
        {"item_id": 909, "refine": 0, "cards": "None", "price": 140, "qty": 1},
    ]
    stats = market_stats([L(price=100)], sales=sales, window_days=4)[909]
    assert stats.realized_price == 150
    assert stats.sell_per_day == 1.0  # 4 qty / 4 days
    assert item_value(stats) == 150   # liquidity 1.0


def test_spot_ev_math():
    spot = {"name": "Anolian River", "map": "cmd_fild01", "monster_ids": [1206],
            "min_level": 70, "kills_per_hour": 400, "arrows_per_hour": 2000,
            "arrow_price": 2, "calibrated": False}
    drops_by_monster = {1206: [
        {"item_id": 7003, "item_name": "Anolian Skin", "rate": 100.0},
        {"item_id": 4234, "item_name": "Anolian Card", "rate": 0.05},
    ]}
    values = {7003: 500, 4234: 1_000_000}
    ev = spot_ev(spot, drops_by_monster, values)
    # RELIABLE headline = non-card only: skins 1.0*500*400 = 200_000 minus arrows 4_000.
    assert ev.zeny_per_hour == 200_000 - 4_000
    # The card is a separate lottery, not folded into the headline.
    assert ev.card_ev_per_hour == 200_000  # 0.0005*1M*400
    assert len(ev.lottery) == 1
    assert ev.lottery[0]["name"] == "Anolian Card"
    assert ev.lottery[0]["kills_to_first"] == 2000
    assert ev.lottery[0]["value"] == 1_000_000
    # reliable top drops exclude the card
    assert all(name != "Anolian Card" for name, _z, _b in ev.top_drops)


def test_ds_damage_matches_calibrated_yao_jun_observation():
    """Model fitted to the player's measured Double Strafe on Yao Jun (~2,500,
    DEF 12, medium). Bows do 75% vs large in pre-re."""
    from ro_collector.scoring import ds_damage
    assert abs(ds_damage(def_=12, size="medium") - 2500) <= 25
    # large mob, same def: 75% bow size penalty
    assert abs(ds_damage(def_=12, size="large") - 2500 * 0.75) <= 25


def test_ds_damage_floors_at_one_for_def_100_plants():
    """Plant-type mobs have DEF 100 (take 1 damage per hit in RO) — the model
    must floor at 1 damage, not divide by zero."""
    from ro_collector.scoring import ds_damage, model_kills_per_hour
    assert ds_damage(def_=100, size="small") >= 1
    assert model_kills_per_hour(hp=10, def_=100, size="small") > 0


def test_model_kills_per_hour_yao_jun():
    """Yao Jun: 9,981 HP / ~2,500 per DS = 4 DS, minus 1 (buffed play) = 3 DS.
    Kill cycle = DS casts + retarget overhead; result is an upper bound
    (unlimited spawns) in the hundreds per hour."""
    from ro_collector.scoring import ds_per_kill, model_kills_per_hour
    assert ds_per_kill(hp=9981, def_=12, size="medium") == 3
    kph = model_kills_per_hour(hp=9981, def_=12, size="medium")
    assert 400 <= kph <= 700
    # a tanky large mob kills slower
    assert model_kills_per_hour(hp=60_000, def_=30, size="large") < kph


def test_lottery_grinds_falls_back_to_model_kills_per_hour():
    """Mobs outside the 16 curated spots have no seeded kph — hours_to_first
    must fall back to the damage model instead of staying blank, and the row
    must say which source it used."""
    drops = [
        {"monster_id": 1189, "monster_name": "Orc Archer", "item_id": 1734, "item_name": "Orc Archer Bow", "rate": 0.1},
    ]
    markets = market_stats([L(item_id=1734, name="Orc Archer Bow", price=7_000_000, amount=1)], [], 7)
    meta = {1189: {"boss_class": "normal", "hp": 1729, "def": 9, "size": "medium"}}
    rows = lottery_grinds(drops, markets, {}, [], meta, {1189: {"map_name": "gef_fild10", "amount": 60}})
    bow = rows[0]
    assert bow["hours_to_first"] is not None
    assert bow["kph"] > 0
    assert bow["kph_source"] == "model"
    assert bow["hours_to_first"] == round(bow["kills_to_first"] / bow["kph"], 1)


def test_lottery_grinds_prefers_spot_kph_over_model():
    drops = [
        {"monster_id": 1206, "monster_name": "Anolian", "item_id": 4234, "item_name": "Anolian Card", "rate": 0.05},
    ]
    markets = market_stats([L(item_id=4234, name="Anolian Card", price=5_000_000)], [], 7)
    spots = [{"name": "Anolians", "monster_ids": [1206], "kills_per_hour": 900}]
    meta = {1206: {"boss_class": "normal", "hp": 18960, "def": 15, "size": "large"}}
    rows = lottery_grinds(drops, markets, {}, spots, meta, {})
    assert rows[0]["kph"] == 900
    assert rows[0]["kph_source"] == "spot"


def test_spot_ev_reclassifies_rare_valuable_gear_as_lottery():
    """A low-rate high-value non-card drop must NOT inflate the reliable z/hr
    headline — it's a gamble, same as a card."""
    spot = {"name": "Orc Archers", "map": "gef_fild10", "monster_ids": [1189], "min_level": 1,
            "kills_per_hour": 500, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False}
    drops = {1189: [
        {"item_id": 1734, "item_name": "Orc Archer Bow", "rate": 0.1},
        {"item_id": 1063, "item_name": "Sharp Arrow", "rate": 100.0},
    ]}
    values = {1734: 7_000_000, 1063: 10}
    ev = spot_ev(spot, drops, values)
    assert ev.zeny_per_hour == 10 * 500          # arrows only; bow excluded from reliable
    assert [c["name"] for c in ev.lottery] == ["Orc Archer Bow"]
    assert ev.lottery[0]["kills_to_first"] == 1000
    assert all(name != "Orc Archer Bow" for name, _z, _b in ev.top_drops)


def test_spot_ev_carries_primary_monster_level_and_hp():
    spot = {"name": "S", "map": "m", "monster_ids": [1206], "min_level": 1,
            "kills_per_hour": 100, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False}
    meta = {1206: {"level": 63, "hp": 18960, "base_exp": 900, "best_element": "fire"}}
    ev = spot_ev(spot, {}, {}, meta_by_id=meta)
    assert ev.level == 63
    assert ev.hp == 18960


def test_spot_ev_level_hp_none_without_meta():
    spot = {"name": "S", "map": "m", "monster_ids": [1], "min_level": 1,
            "kills_per_hour": 100, "arrows_per_hour": 0, "arrow_price": 0, "calibrated": False}
    ev = spot_ev(spot, {}, {})
    assert ev.level is None
    assert ev.hp is None


def test_item_stats_aggregates_market_demand_and_velocity():
    from ro_collector.scoring import item_stats
    listings = [
        L(item_id=909, name="Jellopy", price=100, amount=50),
        L(item_id=909, name="Jellopy", price=120, amount=30),
        Listing("B2", "s", "m", 1, 1, 909, "Jellopy", 0, "None", 10, 90),  # 3rd seller
    ]
    sales = [
        {"item_id": 909, "refine": 0, "cards": "None", "price": 110, "qty": 4},
        {"item_id": 909, "refine": 0, "cards": "None", "price": 115, "qty": 2},
        {"item_id": 909, "refine": 0, "cards": "None", "price": 105, "qty": 1},
    ]
    buy_orders = [L(item_id=909, name="Jellopy", price=95, amount=100)]
    st = item_stats(listings, sales, buy_orders, npc_sell={909: 40}, window_days=7)[909]
    assert st["item_name"] == "Jellopy"
    assert st["low"] == 90 and st["supply"] == 90
    assert st["sellers"] == 2            # merchants M and B2 (M listed twice)
    assert st["realized_med"] == 110     # median of 105,110,115
    assert st["n_sales"] == 3
    assert st["velocity_day"] == 1.0     # 7 qty / 7 days
    assert st["best_bid"] == 95 and st["bid_total"] == 9_500
    assert st["npc_sell"] == 40


def test_market_maker_finds_velocity_spread_plays():
    from ro_collector.scoring import market_maker, item_stats, VENDING_TAX
    listings = [
        L(item_id=909, name="Jellopy", price=80, amount=100),
        L(item_id=909, name="Jellopy", price=95, amount=50),
        L(item_id=909, name="Jellopy", price=200, amount=10),   # above med, not cheap
    ]
    sales = [{"item_id": 909, "refine": 0, "cards": "None", "price": 120, "qty": q} for q in (5, 4, 5)]
    stats = item_stats(listings, sales, [], window_days=7)
    rows = market_maker(listings, stats)
    assert len(rows) == 1
    r = rows[0]
    assert r["cheap_qty"] == 150 and r["capital"] == 80 * 100 + 95 * 50
    avg_cost = r["capital"] / 150
    exit_after_tax = 120 * (1 - VENDING_TAX)
    assert r["spread"] == round(exit_after_tax - avg_cost)
    assert r["velocity_day"] == 2.0
    assert r["profit_day"] == round(min(2.0, 150) * r["spread"])
    assert r["days_to_turn"] == 75.0


def test_market_maker_requires_proof():
    from ro_collector.scoring import market_maker, item_stats
    listings = [L(item_id=909, name="Jellopy", price=80, amount=100)]
    sales = [{"item_id": 909, "refine": 0, "cards": "None", "price": 120, "qty": 9}]  # 1 sale event only
    stats = item_stats(listings, sales, [])
    assert market_maker(listings, stats) == []   # n_sales < 3


def test_corners_finds_buyable_monopolies():
    from ro_collector.scoring import corners, item_stats, VENDING_TAX
    listings = [
        L(item_id=909, name="Jellopy", price=100, amount=300),
        Listing("B2", "s", "gef", 5, 5, 909, "Jellopy", 0, "None", 200, 120),
    ]
    sales = [{"item_id": 909, "refine": 0, "cards": "None", "price": 150, "qty": q} for q in (10, 8, 10)]
    stats = item_stats(listings, sales, [], window_days=7)
    rows = corners(listings, stats)
    assert len(rows) == 1
    r = rows[0]
    assert r["sellers"] == 2 and r["qty"] == 500
    assert r["cost"] == 100 * 300 + 120 * 200
    assert r["relist"] == min(round(150 * 1.5), 100 * 3)
    assert r["payoff"] == round(500 * r["relist"] * (1 - VENDING_TAX) - r["cost"])
    assert r["days_monopoly"] == round(500 / 4.0, 1)
    assert r["confidence"] == "proven"


def test_corners_requires_scarcity_and_demand():
    from ro_collector.scoring import corners, item_stats
    # 9 sellers -> not cornerable
    listings = [Listing(f"M{i}", "s", "m", 1, 1, 909, "Jellopy", 0, "None", 10, 100) for i in range(9)]
    sales = [{"item_id": 909, "refine": 0, "cards": "None", "price": 150, "qty": q} for q in (10, 8, 10)]
    assert corners(listings, item_stats(listings, sales, [])) == []
    # 2 sellers but zero demand proof
    listings = listings[:2]
    assert corners(listings, item_stats(listings, [], [])) == []


def test_merchant_profiles_find_habitual_undercutters():
    from ro_collector.scoring import merchant_profiles
    history = [
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 60, "amount": 10, "d": "2026-07-05"},
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 70, "amount": 5, "d": "2026-07-06"},
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 714, "price": 999, "amount": 1, "d": "2026-07-06"},
        # two extra listings so CheapBot clears MERCH_MIN_SEEN (5)
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 60, "amount": 10, "d": "2026-07-04"},
        {"merchant": "CheapBot", "shop": "s", "map": "prt", "x": 1, "y": 1, "item_id": 909, "price": 60, "amount": 10, "d": "2026-07-04"},
        {"merchant": "FairGuy", "shop": "s", "map": "gef", "x": 2, "y": 2, "item_id": 909, "price": 100, "amount": 10, "d": "2026-07-06"},
    ] + [{"merchant": "FairGuy", "shop": "s", "map": "gef", "x": 2, "y": 2, "item_id": 909, "price": 100 + i, "amount": 1, "d": "2026-07-06"} for i in range(4)]
    stats = {909: {"realized_med": 100, "n_sales": 3}, 714: {"realized_med": None}}
    rows = merchant_profiles(history, stats)
    assert rows[0]["merchant"] == "CheapBot"
    cb = rows[0]
    assert cb["seen"] == 5 and cb["hits"] == 4
    assert cb["avg_discount_pct"] == 37.5          # (40+40+40+30)/4 % vs realized_med 100
    assert cb["undercut_value"] == 40 * 10 + 40 * 10 + 40 * 10 + 30 * 5
    assert cb["last_seen"] == "2026-07-06" and "prt" in cb["last_where"]
    assert all(r["merchant"] != "FairGuy" or r["hits"] >= 2 for r in rows)  # FairGuy filtered (0 hits)


def test_exp_per_zeny_brackets_and_sort():
    turnins = [
        {"form": "item", "target_name": "Bacillus", "item_id": 7117, "qty": 50,
         "base_exp": 500_532, "job_exp": 288_904, "min_level": 60, "max_level": 74,
         "npc_purchase_note": None, "npc": "Local Villager", "location": "ein_fild01"},
        {"form": "item", "target_name": "Fluff", "item_id": 914, "qty": 25,
         "base_exp": 770, "job_exp": 60, "min_level": 2, "max_level": 20,
         "npc_purchase_note": None, "npc": "Langry", "location": "gef_fild07"},
    ]
    markets = market_stats([L(item_id=7117, name="Bacillus", price=1000)], [], 7)
    rows = exp_per_zeny(turnins, markets, char_level=72)
    assert len(rows) == 1  # Fluff bracket (2-20) excludes level 72
    assert rows[0]["target_name"] == "Bacillus"
    # 50 * 1000 = 50k zeny -> 500_532 exp -> ~10_010 exp per 1k zeny
    assert rows[0]["base_exp_per_1k_zeny"] == 10_010


def test_strategy_pnl_fifo():
    from ro_collector.scoring import strategy_pnl
    trades = [
        {"item_id": 909, "side": "buy", "qty": 10, "price": 100, "strategy": "mm"},
        {"item_id": 909, "side": "buy", "qty": 10, "price": 120, "strategy": "mm"},
        {"item_id": 909, "side": "sell", "qty": 15, "price": 150, "strategy": "mm"},
        {"item_id": 500, "side": "buy", "qty": 1, "price": 44_000, "strategy": "flip"},
    ]
    pnl = strategy_pnl(trades)
    # FIFO: 10 @100 + 5 @120 sold at 150 -> 500 + 150 = 650... compute: (150-100)*10 + (150-120)*5 = 650
    assert pnl["mm"]["realized"] == 650
    assert pnl["mm"]["open_qty"] == 5 and pnl["mm"]["open_cost"] == 5 * 120
    assert pnl["flip"]["realized"] == 0 and pnl["flip"]["open_cost"] == 44_000
