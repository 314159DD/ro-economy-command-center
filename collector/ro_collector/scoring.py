"""Pure scoring math: market stats, item values, farm-spot EV, exp-per-zeny."""
import math
from dataclasses import dataclass

from .models import Listing


@dataclass(frozen=True)
class ItemMarket:
    item_id: int
    item_name: str
    low: int | None
    median: int | None
    supply: int
    sell_per_day: float | None
    realized_price: int | None


def is_card(item_name: str) -> bool:
    return "Card" in item_name


# A "lottery" is any low-odds, high-payout drop — cards always, but also rare
# valuable gear (the Orc Archer Bow case: 7M zeny at 0.1%). These are gambles,
# not income: they must not inflate the reliable z/hr headline, and they get
# their own global board (lottery_grinds).
LOTTERY_MAX_RATE = 0.5      # percent; at 0.5% you're ~200+ kills per attempt
LOTTERY_MIN_VALUE = 100_000  # zeny; below this a rare drop is trivia, not a jackpot


def is_lottery(item_name: str, rate: float, value: int) -> bool:
    if is_card(item_name):
        return True
    return rate <= LOTTERY_MAX_RATE and value >= LOTTERY_MIN_VALUE


@dataclass(frozen=True)
class SpotEV:
    spot_name: str
    map: str
    min_level: int
    zeny_per_hour: int           # RELIABLE income only (non-card drops) - arrow cost
    calibrated: bool
    top_drops: list  # top reliable [(item_name, zeny/hr, demand_backed)]
    card_notes: list  # legacy; kept populated for compatibility
    notes: str = ""  # freeform seed notes, e.g. hunt-combo callouts
    lottery: list = None  # card gambles: [{name, value, kills_to_first, ev_per_hour, backed}]
    card_ev_per_hour: int = 0     # summed expected value of card drops (the upside)
    # RagnaAPI enrichment (0/"" when not yet enriched):
    exp_per_hour: int = 0        # base EXP/hr from mob kills at this spot
    best_map: str = ""           # densest known spawn map (RagnaAPI)
    density: int = 0             # mob count on that map
    arrow: str = ""              # element the mobs are weakest to (best arrow)
    level: int | None = None     # primary monster's level
    hp: int | None = None        # primary monster's HP
    kph: int = 0                 # seeded/calibrated kills per hour
    arrow_cost: int = 0          # arrows_per_hour x arrow_price
    monster_id: int | None = None  # primary monster (sprite/tooltip lookups)


def _median(sorted_vals: list[int]) -> int:
    return sorted_vals[len(sorted_vals) // 2]


def market_stats(listings: list[Listing], sales: list[dict], window_days: int) -> dict:
    """Comparable = +0, no cards. sales rows: dicts with item_id/refine/cards/price/qty."""
    by_item: dict[int, list[Listing]] = {}
    for l in listings:
        by_item.setdefault(l.item_id, []).append(l)

    comp_sales: dict[int, list[dict]] = {}
    for s in sales:
        if s["refine"] == 0 and s["cards"] == "None":
            comp_sales.setdefault(s["item_id"], []).append(s)

    cold_start = len(sales) == 0
    out: dict[int, ItemMarket] = {}
    for item_id, ls in by_item.items():
        comp = [l for l in ls if l.refine == 0 and l.cards == "None"]
        prices = sorted(l.price for l in comp)
        s = comp_sales.get(item_id, [])
        sold_qty = sum(x["qty"] for x in s)
        sale_prices = sorted(x["price"] for x in s)
        out[item_id] = ItemMarket(
            item_id=item_id,
            item_name=ls[0].item_name,
            low=prices[0] if prices else None,
            median=_median(prices) if prices else None,
            supply=sum(l.amount for l in comp),
            sell_per_day=None if cold_start else sold_qty / window_days,
            realized_price=_median(sale_prices) if len(s) >= 3 else None,
        )
    return out


# A vendor listing with no standing buyer and no sales history is unproven: the
# asking price is aspirational (a junk item like Club[3] can sit at 33k forever
# with zero buyers). Value it at a small fraction until demand or a real sale
# proves it. Once >=3 sales land, realized_price takes over and this stops
# applying; once a buy order appears, demand_price bypasses it entirely.
UNPROVEN_FACTOR = 0.1


def demand_map(buy_orders: list) -> dict:
    """item_id -> best (highest) standing buyer price. A buy order is proof the
    item sells right now, and its price is a guaranteed sale, not a hope."""
    out: dict[int, int] = {}
    for b in buy_orders:
        if b.price > out.get(b.item_id, 0):
            out[b.item_id] = b.price
    return out


def liquidity_factor(sell_per_day: float | None) -> float:
    if sell_per_day is None:
        return 0.5
    return max(0.2, min(1.0, sell_per_day))


def item_value(market: ItemMarket, demand_price: int | None = None) -> int:
    """Confident when demand-backed or sales-proven; skeptical of vendor-only asks.

    - demand_price present  -> guaranteed sale to a standing buy order.
    - >=3 recorded sales    -> realized median price x observed liquidity.
    - vendor-only, no sales -> low x UNPROVEN_FACTOR (don't let junk dominate).
    """
    if demand_price:
        return demand_price
    if market.realized_price is not None:
        return round(market.realized_price * liquidity_factor(market.sell_per_day))
    return round((market.low or 0) * UNPROVEN_FACTOR)


# --- Calibrated Double Strafe damage model (fitted 2026-07-06) ---------------
# Fitted to one measured DS on Yao Jun: ~2,500 total damage (DEF 12, medium,
# unbuffed). EFF_ATK = status ATK 272 (DEX 126 / STR 6 / LUK 8) + Orc Archer
# Bow +5 (135) + Steel Arrow (40). EFF_MULT bundles the DS skill ratio,
# the server's custom bow bonus (+50% ranged w/ Steel Arrows) and anything else we
# can't see server-side. To recalibrate after a gear/level change: update
# _OBSERVED_DS (and _CALIB_DEF if measured on a different mob), rerun tests.
EFF_ATK = 447
_CALIB_DEF = 12
_OBSERVED_DS = 2500
EFF_MULT = _OBSERVED_DS / (EFF_ATK * (1 - _CALIB_DEF / 100))  # ~6.36

BOW_SIZE_MOD = {"small": 1.0, "medium": 1.0, "large": 0.75}  # pre-re bow penalty
DS_BUFF_BONUS = 1       # buffed play saves ~one DS per kill (measured: 4 -> 3)
DS_SECONDS = 1.0        # one DS cycle at high ASPD
RETARGET_SECONDS = 3.0  # find/walk to the next target on a DENSE map — the
                        # model is an unlimited-spawn upper bound; scarce or
                        # contested maps need a manual kills/min override


def ds_damage(def_: int | None, size: str | None) -> int:
    """Predicted total Double Strafe damage vs a mob (calibrated model).
    Floored at 2 (RO's 1-damage-per-hit minimum x 2 hits — the DEF-100
    plant-mob case)."""
    return max(2, round(EFF_ATK * EFF_MULT * BOW_SIZE_MOD.get(size or "medium", 1.0)
                        * (1 - (def_ or 0) / 100)))


def ds_per_kill(hp: int, def_: int | None, size: str | None) -> int:
    return max(1, math.ceil(hp / ds_damage(def_, size)) - DS_BUFF_BONUS)


def model_kills_per_hour(hp: int, def_: int | None, size: str | None) -> int:
    return round(3600 / (ds_per_kill(hp, def_, size) * DS_SECONDS + RETARGET_SECONDS))


def value_map(markets: dict, demand: dict) -> dict:
    """item_id -> zeny value for EV math. Vendor-listed items go through
    item_value(); items demanded via buy order but never vendor-listed are
    worth the bid itself (a buy order is a guaranteed sale either way)."""
    values = {item_id: item_value(m, demand.get(item_id)) for item_id, m in markets.items()}
    for item_id, price in demand.items():
        values.setdefault(item_id, price)
    return values


DISCOVER_MIN_DENSITY = 15
DISCOVER_MIN_ZHR = 50_000


def discover_spots(drops: list[dict], values: dict, demand_ids: set, meta_by_id: dict,
                   best_spawn_by_id: dict, exclude_monster_ids: set, char_level: int) -> list[dict]:
    """Rank EVERY farmable mob by model z/hr; surfaces spots the curated 16
    miss. density_factor keeps sparse maps honest; arrow cost unknown per mob
    and deliberately ignored (stated in the UI)."""
    by_monster: dict[int, list] = {}
    for d in drops:
        by_monster.setdefault(d["monster_id"], []).append(d)
    rows = []
    for mid, ds in by_monster.items():
        if mid in exclude_monster_ids:
            continue
        meta = meta_by_id.get(mid) or {}
        spawn = best_spawn_by_id.get(mid) or {}
        density = spawn.get("amount", 0)
        if (meta.get("boss_class", "normal") != "normal" or density < DISCOVER_MIN_DENSITY
                or not meta.get("hp") or (meta.get("level") or 0) > char_level + 20):
            continue
        kph = model_kills_per_hour(meta["hp"], meta.get("def"), meta.get("size"))
        factor = min(1.0, density / 40.0)
        contribs = []
        for d in ds:
            value = values.get(d["item_id"], 0)
            if value <= 0 or is_lottery(d["item_name"], d["rate"], value):
                continue
            contribs.append({"name": d["item_name"],
                             "zhr": round(d["rate"] / 100.0 * value * kph * factor),
                             "backed": d["item_id"] in demand_ids})
        contribs.sort(key=lambda c: -c["zhr"])
        zhr = sum(c["zhr"] for c in contribs)
        if zhr < DISCOVER_MIN_ZHR:
            continue
        rows.append({
            "monster_id": mid, "monster": ds[0]["monster_name"],
            "map": spawn.get("map_name", ""), "density": density,
            "level": meta.get("level"), "hp": meta.get("hp"),
            "kph": round(kph * factor), "zhr": zhr,
            "exp_hr": round((meta.get("base_exp") or 0) * kph * factor),
            "top_drops": contribs[:3],
        })
    rows.sort(key=lambda r: -r["zhr"])
    return rows


VENDING_TAX = 0.02  # assumed until verified on the wiki; single source


def item_stats(listings: list, sales: list[dict], buy_orders: list,
               npc_sell: dict | None = None, window_days: int = 7) -> dict[int, dict]:
    """Per-item market/demand/velocity numbers shared by Market Maker,
    Corners, Merchants and the digest. Comparable listings only."""
    npc_sell = npc_sell or {}
    markets = market_stats(listings, sales, window_days)
    demand = demand_map(buy_orders)
    sellers: dict[int, set] = {}
    for l in listings:
        if l.refine == 0 and l.cards == "None":
            sellers.setdefault(l.item_id, set()).add(l.merchant)
    sold_qty: dict[int, int] = {}
    sale_prices: dict[int, list] = {}
    for s in sales:
        if s["refine"] == 0 and s["cards"] == "None":
            sold_qty[s["item_id"]] = sold_qty.get(s["item_id"], 0) + s["qty"]
            sale_prices.setdefault(s["item_id"], []).append(s["price"])
    bid_total: dict[int, int] = {}
    for b in buy_orders:
        bid_total[b.item_id] = bid_total.get(b.item_id, 0) + b.amount * b.price
    out: dict[int, dict] = {}
    for item_id, m in markets.items():
        prices = sorted(sale_prices.get(item_id, []))
        out[item_id] = {
            "item_name": m.item_name,
            "low": m.low, "median": m.median, "supply": m.supply,
            "sellers": len(sellers.get(item_id, set())),
            "realized_med": prices[len(prices) // 2] if prices else None,
            "n_sales": len(prices),
            "velocity_day": round(sold_qty.get(item_id, 0) / window_days, 2),
            "best_bid": demand.get(item_id),
            "bid_total": bid_total.get(item_id, 0),
            "npc_sell": npc_sell.get(item_id),
        }
    return out


MM_MIN_SALES = 3
MM_MIN_VELOCITY = 1.0
MM_MIN_SPREAD_PCT = 0.10


def market_maker(listings: list, stats: dict) -> list[dict]:
    """The compounder: items that provably SELL (velocity) and are currently
    listed below their realized price. Buy the cheap stock, vend at realized,
    repeat. profit_day caps at velocity: you cannot sell faster than the
    market buys."""
    comp: dict[int, list] = {}
    for l in listings:
        if l.refine == 0 and l.cards == "None":
            comp.setdefault(l.item_id, []).append(l)
    rows = []
    for item_id, st in stats.items():
        med = st["realized_med"]
        if (st["n_sales"] < MM_MIN_SALES or st["velocity_day"] < MM_MIN_VELOCITY
                or not med):
            continue
        exit_price = med * (1 - VENDING_TAX)
        cheap = [l for l in comp.get(item_id, []) if l.price < exit_price]
        if not cheap:
            continue
        qty = sum(l.amount for l in cheap)
        capital = sum(l.price * l.amount for l in cheap)
        avg_cost = capital / qty
        spread = round(exit_price - avg_cost)
        if spread < med * MM_MIN_SPREAD_PCT:
            continue
        c = min(cheap, key=lambda l: l.price)
        rows.append({
            "item": st["item_name"], "item_id": item_id,
            "low": st["low"], "cheap_qty": qty, "capital": capital,
            "avg_cost": round(avg_cost), "realized_med": med,
            "velocity_day": st["velocity_day"], "n_sales": st["n_sales"],
            "spread": spread,
            "profit_day": round(min(st["velocity_day"], qty) * spread),
            "days_to_turn": round(qty / st["velocity_day"], 1),
            "roi_day": round(min(st["velocity_day"], qty) * spread / capital, 4) if capital else 0,
            "where": f"{c.map} ({c.x},{c.y})", "shop": c.shop,
        })
    rows.sort(key=lambda r: -r["profit_day"])
    return rows


CORNER_MAX_SELLERS = 8
CORNER_MIN_VELOCITY = 2.0
CORNER_RELIST_MULT = 1.5
CORNER_MAX_OVER_LOW = 3
CORNER_HARD_CAP = 200_000_000  # ship superset; the UI filters by the capital setting


def corners(listings: list, stats: dict) -> list[dict]:
    """Scarcity plays: few sellers, proven demand, total supply buyable. Buy it
    all, relist at CORNER_RELIST_MULT x realized (capped vs low). Payoff is the
    full-monopoly estimate; the UI labels confidence and filters by capital."""
    comp: dict[int, list] = {}
    for l in listings:
        if l.refine == 0 and l.cards == "None":
            comp.setdefault(l.item_id, []).append(l)
    rows = []
    for item_id, st in stats.items():
        ls = comp.get(item_id)
        if not ls or st["sellers"] > CORNER_MAX_SELLERS:
            continue
        qty = sum(l.amount for l in ls)
        cost = sum(l.price * l.amount for l in ls)
        if not qty or cost > CORNER_HARD_CAP:
            continue
        proven = st["n_sales"] >= 3 and st["velocity_day"] >= CORNER_MIN_VELOCITY
        bid_backed = st["bid_total"] >= cost
        if not proven and not bid_backed:
            continue
        ref = st["realized_med"] or st["best_bid"] or 0
        if not ref:
            continue
        relist = min(round(ref * CORNER_RELIST_MULT), (st["low"] or 0) * CORNER_MAX_OVER_LOW)
        payoff = round(qty * relist * (1 - VENDING_TAX) - cost)
        if payoff <= 0:
            continue
        rows.append({
            "item": st["item_name"], "item_id": item_id,
            "sellers": st["sellers"], "qty": qty, "cost": cost,
            "low": st["low"], "realized_med": st["realized_med"],
            "velocity_day": st["velocity_day"], "n_sales": st["n_sales"],
            "bid_total": st["bid_total"],
            "days_monopoly": round(qty / st["velocity_day"], 1) if st["velocity_day"] else None,
            "relist": relist, "payoff": payoff,
            "maps": ", ".join(sorted({l.map for l in ls})),
            "confidence": "proven" if proven else "bid-backed",
        })
    rows.sort(key=lambda r: -r["payoff"])
    return rows


MERCH_MIN_SEEN = 5
MERCH_MIN_HITS = 2


def merchant_profiles(history: list[dict], stats: dict) -> list[dict]:
    """Sellers who habitually list below realized value: bots and lazy farmers
    with fixed price lists. Their shops are a standing snipe subscription."""
    by_m: dict[str, dict] = {}
    for h in history:
        p = by_m.setdefault(h["merchant"], {"seen": 0, "items": set(), "hits": 0,
                                            "discounts": [], "undercut": 0,
                                            "last_seen": "", "last_where": ""})
        p["seen"] += 1
        p["items"].add(h["item_id"])
        st = stats.get(h["item_id"]) or {}
        med = st.get("realized_med")
        if med and st.get("n_sales", 0) >= 3 and h["price"] < med:
            p["hits"] += 1
            p["discounts"].append((med - h["price"]) / med)
            p["undercut"] += (med - h["price"]) * h["amount"]
        if h["d"] >= p["last_seen"]:
            p["last_seen"] = h["d"]
            p["last_where"] = f'{h["map"]} ({h["x"]},{h["y"]})'
    rows = []
    for name, p in by_m.items():
        if p["seen"] < MERCH_MIN_SEEN or p["hits"] < MERCH_MIN_HITS:
            continue
        rows.append({
            "merchant": name, "seen": p["seen"], "items": len(p["items"]),
            "hits": p["hits"], "hit_rate": round(p["hits"] / p["seen"], 2),
            "avg_discount_pct": round(sum(p["discounts"]) / len(p["discounts"]) * 100, 1),
            "undercut_value": round(p["undercut"]),
            "last_seen": p["last_seen"], "last_where": p["last_where"],
        })
    rows.sort(key=lambda r: -r["undercut_value"])
    return rows


def spot_ev(spot: dict, drops_by_monster: dict, values: dict, demand_ids: set | None = None,
            meta_by_id: dict | None = None, best_spawn_by_id: dict | None = None) -> SpotEV:
    demand_ids = demand_ids or set()
    meta_by_id = meta_by_id or {}
    best_spawn_by_id = best_spawn_by_id or {}
    kph_per_monster = spot["kills_per_hour"] / len(spot["monster_ids"])
    contributions: list[tuple[str, float, bool]] = []   # reliable (non-card) earners
    card_notes: list[str] = []
    lottery: list[dict] = []                            # card gambles, EV-based
    exp_per_hour = 0.0
    for mid in spot["monster_ids"]:
        meta = meta_by_id.get(mid)
        if meta:
            exp_per_hour += (meta.get("base_exp") or 0) * kph_per_monster
        for d in drops_by_monster.get(mid, []):
            value = values.get(d["item_id"], 0)
            zhr = (d["rate"] / 100.0) * value * kph_per_monster
            if is_lottery(d["item_name"], d["rate"], value) and d["rate"] > 0:
                kills = round(1 / (d["rate"] / 100.0))
                lottery.append({
                    "name": d["item_name"], "value": value, "rate": d["rate"],
                    "kills_to_first": kills, "ev_per_hour": round(zhr),
                    "hours_to_first": round(kills / spot["kills_per_hour"], 1) if spot["kills_per_hour"] else 0,
                    "backed": d["item_id"] in demand_ids,
                })
                card_notes.append(f"{d['item_name']}: ~{kills:,} kills to first")
            elif zhr > 0:
                contributions.append((d["item_name"], zhr, d["item_id"] in demand_ids))
    contributions.sort(key=lambda c: -c[1])
    lottery.sort(key=lambda c: -c["value"])
    reliable = sum(z for _, z, _ in contributions)
    card_ev = sum(c["ev_per_hour"] for c in lottery)
    cost = spot["arrows_per_hour"] * spot["arrow_price"]

    # Densest known spawn across the spot's monsters (RagnaAPI); arrow = the
    # primary monster's biggest elemental weakness.
    best_map, density = "", 0
    for mid in spot["monster_ids"]:
        sp = best_spawn_by_id.get(mid)
        if sp and sp.get("amount", 0) > density:
            best_map, density = sp["map_name"], sp["amount"]
    primary_meta = meta_by_id.get(spot["monster_ids"][0]) if spot["monster_ids"] else None
    arrow = (primary_meta or {}).get("best_element", "") if primary_meta else ""

    return SpotEV(
        spot_name=spot["name"],
        map=spot["map"],
        min_level=spot["min_level"],
        zeny_per_hour=round(reliable - cost),   # reliable income headline
        calibrated=spot["calibrated"],
        top_drops=[(n, round(z), backed) for n, z, backed in contributions[:3]],
        card_notes=card_notes,
        notes=spot.get("notes", ""),
        lottery=lottery,
        card_ev_per_hour=card_ev,
        exp_per_hour=round(exp_per_hour),
        best_map=best_map,
        density=density,
        arrow=arrow,
        level=(primary_meta or {}).get("level"),
        hp=(primary_meta or {}).get("hp"),
        kph=spot["kills_per_hour"],
        arrow_cost=cost,
        monster_id=spot["monster_ids"][0] if spot["monster_ids"] else None,
    )


def kills_from_loot(loot: dict, drops: list[dict]) -> int | None:
    """Back-calculate kills from a drop count: kills = count / (rate/100). Use the
    highest-rate matched item (closest to a per-kill counter, least noisy)."""
    by_name = {d["item_name"].lower(): d["rate"] for d in drops if d["rate"] > 0}
    best_rate, best_est = 0.0, None
    for name, count in loot.items():
        rate = by_name.get(name.lower())
        if rate and rate > best_rate:
            best_rate = rate
            best_est = round(count / (rate / 100.0))
    return best_est


def lottery_grinds(drops: list[dict], markets: dict, demand: dict, spots: list[dict],
                   meta_by_id: dict | None = None, best_spawn_by_id: dict | None = None) -> list[dict]:
    """The lottery board: every low-odds high-payout drop — cards AND rare
    valuable gear (Orc Archer Bow: 7M at 0.1%) — ranked by market value, with
    where it drops, whether the source is farmable, and how long a first one
    takes. value prefers a live buyer price, else the lowest vendor ask (an ask
    on a card or big-ticket gear is a real signal); supply shows how many
    vendors already sit on it, so saturation is visible. Each row carries the
    source monster's type/level/HP + densest spawn so you can tell a normal
    grind from an MVP/boss hunt."""
    meta_by_id = meta_by_id or {}
    best_spawn_by_id = best_spawn_by_id or {}
    kph_by_monster: dict[int, int] = {}
    for s in spots:
        per = s["kills_per_hour"] / max(1, len(s["monster_ids"]))
        for mid in s["monster_ids"]:
            kph_by_monster[mid] = max(kph_by_monster.get(mid, 0), round(per))

    # item_id -> best (highest-rate) QUALIFYING drop source. Qualification is
    # per drop, not per item: Orc Archer Bow also falls out of Treasure Chest
    # at 7.5%, but that source isn't a lottery (and isn't grindable) — the
    # 0.1% Orc Archer drop still is.
    best: dict[int, dict] = {}
    values: dict[int, int] = {}
    for d in drops:
        if d["rate"] <= 0:
            continue
        item_id = d["item_id"]
        if item_id not in values:
            m = markets.get(item_id)
            values[item_id] = demand.get(item_id) or (m.low if m and m.low else 0)
        value = values[item_id]
        if value <= 0 or not is_lottery(d["item_name"], d["rate"], value):
            continue
        cur = best.get(item_id)
        if cur is None or d["rate"] > cur["rate"]:
            best[item_id] = d

    rows = []
    for item_id, d in best.items():
        m = markets.get(item_id)
        value = values[item_id]
        mid = d["monster_id"]
        meta = meta_by_id.get(mid) or {}
        spawn = best_spawn_by_id.get(mid) or {}
        boss_class = meta.get("boss_class", "normal")
        density = spawn.get("amount", 0)
        # Farmable = an ordinary mob that actually spawns in numbers; MVPs and
        # mini-bosses are single-spawn boss hunts, not a grind.
        farmable = boss_class == "normal" and density > 1
        kills = round(1 / (d["rate"] / 100.0))
        # kills/hr: a curated-spot seed if the mob is in one, else the
        # calibrated damage model (unlimited-spawn upper bound).
        kph = kph_by_monster.get(mid)
        kph_source = "spot" if kph else None
        if not kph and meta.get("hp"):
            kph = model_kills_per_hour(meta["hp"], meta.get("def"), meta.get("size"))
            kph_source = "model"
        rows.append({
            "item": d["item_name"],
            "item_id": item_id,
            "monster_id": mid,
            "kind": "card" if is_card(d["item_name"]) else "gear",
            "value": value,
            "supply": m.supply if m else 0,
            "monster": d["monster_name"],
            "rate": d["rate"],
            "kills_to_first": kills,
            "hours_to_first": round(kills / kph, 1) if kph else None,
            "kph": kph,
            "kph_source": kph_source,
            "backed": item_id in demand,
            "boss_class": boss_class,           # normal | miniboss | mvp
            "level": meta.get("level"),
            "hp": meta.get("hp"),
            "spawn_map": spawn.get("map_name", ""),
            "spawn_density": density,
            "farmable": farmable,
        })
    rows.sort(key=lambda r: -r["value"])
    return rows


# Overcharge lv10 (merchant skill): NPCs buy at 124% of the item's sell
# price — anything vended below that line is guaranteed profit with unlimited
# liquidity. Tiny totals aren't worth the walk.
OVERCHARGE_RATE = 1.24
MIN_NPC_FLIP_TOTAL = 10_000


def flips(listings: list, buy_orders: list, markets: dict, npc_sell: dict | None = None) -> list[dict]:
    """Instant, exit-guaranteed profit from one snapshot. Two exits:

    - exit "buyer": the highest standing buy order beats the cheapest
      comparable vendor ask; qty = min(stock at that ask, buyer demand).
    - exit "npc": listings priced below floor(npc_sell x OVERCHARGE_RATE);
      EVERY qualifying listing counts (the NPC buys everything), so qty/cost/
      profit aggregate across all of them.
    """
    comp: dict[int, list] = {}
    for l in listings:
        if l.refine == 0 and l.cards == "None":
            comp.setdefault(l.item_id, []).append(l)

    def cheapest_loc(ls):
        c = min(ls, key=lambda l: l.price)
        return f"{c.map} ({c.x},{c.y})", c.shop

    rows = []

    # exit: standing buy orders
    bid: dict[int, int] = {}
    bid_qty: dict[int, int] = {}
    bid_name: dict[int, str] = {}
    for b in buy_orders:
        if b.price > bid.get(b.item_id, 0):
            bid[b.item_id] = b.price
        bid_qty[b.item_id] = bid_qty.get(b.item_id, 0) + b.amount
        bid_name[b.item_id] = b.item_name
    for item_id, buyer_price in bid.items():
        m = markets.get(item_id)
        ask = m.low if m and m.low else None
        if ask is None or buyer_price <= ask:
            continue
        qty = min(m.supply, bid_qty[item_id])
        if qty <= 0:
            continue
        where, shop = cheapest_loc(comp[item_id])
        rows.append({
            "item": m.item_name or bid_name.get(item_id, ""),
            "item_id": item_id,
            "exit": "buyer",
            "vendor_low": ask,
            "exit_price": buyer_price,
            "profit_per": buyer_price - ask,
            "qty": qty,
            "cost": ask * qty,
            "total_profit": (buyer_price - ask) * qty,
            "where": where,
            "shop": shop,
        })

    # exit: NPC with Overcharge
    for item_id, sell in (npc_sell or {}).items():
        ls = comp.get(item_id)
        if not ls or not sell:
            continue
        exit_price = int(sell * OVERCHARGE_RATE)
        hits = [l for l in ls if l.price < exit_price]
        if not hits:
            continue
        total = sum((exit_price - l.price) * l.amount for l in hits)
        if total < MIN_NPC_FLIP_TOTAL:
            continue
        where, shop = cheapest_loc(hits)
        rows.append({
            "item": hits[0].item_name,
            "item_id": item_id,
            "exit": "npc",
            "vendor_low": min(l.price for l in hits),
            "exit_price": exit_price,
            "profit_per": exit_price - min(l.price for l in hits),
            "qty": sum(l.amount for l in hits),
            "cost": sum(l.price * l.amount for l in hits),
            "total_profit": total,
            "where": where,
            "shop": shop,
        })

    rows.sort(key=lambda r: -r["total_profit"])
    return rows


# Undercut detection: the cheapest ask must be a real outlier, not ordinary
# price competition, and the reference (2nd-lowest) must be corroborated by
# at least one more seller (>=3 comparable listings total).
UNDERCUT_MAX_RATIO = 0.6      # cheapest <= 60% of the next ask
UNDERCUT_MIN_SPREAD = 50_000  # zeny per unit, below this it's not worth the walk


def undercuts(listings: list, demand: dict | None = None) -> list[dict]:
    """Vendor-vs-vendor snipes: an impatient seller listing far below the other
    vendors of the same (comparable +0/no-card) item. Buy his, relist next to
    the rest. Exit is NOT guaranteed (unlike flips) — the reference ask is only
    as real as the sellers behind it, so we require depth and show demand."""
    demand = demand or {}
    by_item: dict[int, list] = {}
    for l in listings:
        if l.refine == 0 and l.cards == "None":
            by_item.setdefault(l.item_id, []).append(l)

    rows = []
    for item_id, ls in by_item.items():
        if len(ls) < 3:
            continue
        ls.sort(key=lambda l: l.price)
        cheap, ref = ls[0], ls[1]
        spread = ref.price - cheap.price
        if cheap.price > ref.price * UNDERCUT_MAX_RATIO or spread < UNDERCUT_MIN_SPREAD:
            continue
        rows.append({
            "item": cheap.item_name,
            "item_id": item_id,
            "price": cheap.price,
            "qty": cheap.amount,
            "cost": cheap.price * cheap.amount,
            "next_price": ref.price,
            "spread": spread,
            "potential": spread * cheap.amount,
            "sellers_above": len(ls) - 1,
            "backed": item_id in demand,
            "where": f"{cheap.map} ({cheap.x},{cheap.y})",
            "shop": cheap.shop,
        })
    rows.sort(key=lambda r: -r["potential"])
    return rows


def strategy_pnl(trades: list[dict]) -> dict:
    """Realized profit per strategy, FIFO within (item, strategy)."""
    lots: dict[tuple, list] = {}
    out: dict[str, dict] = {}
    for t in trades:
        s = out.setdefault(t["strategy"], {"realized": 0, "open_qty": 0, "open_cost": 0})
        key = (t["item_id"], t["strategy"])
        if t["side"] == "buy":
            lots.setdefault(key, []).append([t["qty"], t["price"]])
        else:
            remaining = t["qty"]
            q = lots.get(key, [])
            while remaining and q:
                lot = q[0]
                take = min(lot[0], remaining)
                s["realized"] += take * (t["price"] - lot[1])
                lot[0] -= take
                remaining -= take
                if lot[0] == 0:
                    q.pop(0)
            s["realized"] += remaining * t["price"]  # sold without recorded buy: pure proceeds
    for (item_id, strat), q in lots.items():
        s = out[strat]
        for qty, price in q:
            s["open_qty"] += qty
            s["open_cost"] += qty * price
    return out


def exp_per_zeny(turnins: list[dict], markets: dict, char_level: int) -> list[dict]:
    rows = []
    for q in turnins:
        if q["form"] != "item" or not (q["min_level"] <= char_level <= q["max_level"]):
            continue
        market = markets.get(q["item_id"]) if q["item_id"] else None
        unit = market.low if market and market.low else None
        if unit is None and not q["npc_purchase_note"]:
            continue
        row = dict(q)
        if unit is not None:
            cost = q["qty"] * unit
            row["turnin_cost"] = cost
            row["base_exp_per_1k_zeny"] = (q["base_exp"] * 1000) // cost
        else:
            row["turnin_cost"] = None
            row["base_exp_per_1k_zeny"] = None
            row["note"] = "NPC-priced: check in game"
        rows.append(row)
    rows.sort(key=lambda r: -(r["base_exp_per_1k_zeny"] or 0))
    return rows
