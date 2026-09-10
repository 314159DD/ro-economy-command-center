"""Render an interactive, self-contained HTML dashboard.

The visual counterpart to shortlist.py's markdown report -- same underlying
scoring math (market_stats / demand_map / item_value / spot_ev / exp_per_zeny),
reused as-is so the numbers match, but rendered as a sortable/searchable page
instead of a wall of text. No external assets: everything (CSS, JS, data) is
inlined so the file works fully offline.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .config import load_settings
from .db import Store
from .icons import ensure_icons, ensure_mob_icons, icon_data_uris, mob_icon_data_uris
from .scoring import (corners, demand_map, discover_spots, exp_per_zeny, flips, item_stats, item_value,
                      lottery_grinds, market_maker, market_stats, merchant_profiles, model_kills_per_hour,
                      spot_ev, strategy_pnl, undercuts, value_map)

SALES_WINDOW_DAYS = 7

TAB_LABELS = ("Grind Board", "Lotteries", "Flipping", "Snipes", "Market Maker", "Corners", "Item Explorer",
             "Buyer Orders", "Merchants", "War Chest", "EXP Planner")


def _est_value(item_id, markets: dict, demand: dict) -> int:
    """item_value() needs an ItemMarket; drop-only items (never vendor-listed)
    don't have one, so fall back to the standing buy price, else zero."""
    m = markets.get(item_id)
    if m is not None:
        return item_value(m, demand.get(item_id))
    dp = demand.get(item_id)
    return dp if dp else 0


def _build_grind_board(spots: list[dict], drops: list[dict], values: dict, demand_ids: set, char_level: int,
                       meta_by_id: dict | None = None, best_spawn_by_id: dict | None = None):
    drops_by_monster: dict[int, list] = defaultdict(list)
    for d in drops:
        drops_by_monster[d["monster_id"]].append(d)

    evs = [spot_ev(s, drops_by_monster, values, demand_ids, meta_by_id, best_spawn_by_id) for s in spots]
    open_spots = sorted((e for e in evs if e.min_level <= char_level), key=lambda e: -e.zeny_per_hour)
    locked = sorted((e for e in evs if e.min_level > char_level), key=lambda e: -e.zeny_per_hour)

    def _notes(e):
        parts = []
        if e.exp_per_hour:
            parts.append(f"~{e.exp_per_hour:,} exp/hr")
        if e.arrow:
            parts.append(f"arrow: {e.arrow}")
        if e.notes:
            parts.append(e.notes)
        return " · ".join(parts)

    grind_open = [
        {
            "rank": i,
            "spot": e.spot_name,
            "map": f"{e.best_map} (x{e.density})" if e.best_map else e.map,
            "level": e.level,
            "hp": e.hp,
            "monster_id": e.monster_id,
            "zhr": e.zeny_per_hour,
            "lottery_ev": e.card_ev_per_hour,
            "kph": e.kph,
            "arrow_cost": e.arrow_cost,
            "calibrated": e.calibrated,
            "top_drops": [{"name": n, "zhr": z, "backed": backed} for n, z, backed in e.top_drops],
            "lottery": [
                {
                    "name": c["name"],
                    "value": c["value"],
                    "hours_to_first": c.get("hours_to_first"),
                    "kills_to_first": c.get("kills_to_first"),
                    "backed": c.get("backed", False),
                }
                for c in (e.lottery or [])
            ],
            "notes": _notes(e),
        }
        for i, e in enumerate(open_spots, 1)
    ]
    grind_locked = [
        {"spot": e.spot_name, "map": e.map, "min_level": e.min_level, "zhr": e.zeny_per_hour}
        for e in locked
    ]
    return grind_open, grind_locked


def _best_drop_sources(drops: list[dict]) -> dict[int, tuple]:
    """item_id -> (monster_name, rate, monster_id) of the highest-rate known drop source."""
    best: dict[int, tuple] = {}
    for d in drops:
        cur = best.get(d["item_id"])
        if cur is None or d["rate"] > cur[1]:
            best[d["item_id"]] = (d["monster_name"], d["rate"], d["monster_id"])
    return best


def _build_buyer_orders(buy_orders: list, drops: list[dict], markets: dict,
                        meta_by_id: dict | None = None, spots: list[dict] | None = None):
    """One row per demanded item: standing buy orders aggregated - best bid,
    total qty wanted, order count, total zeny on the table - plus vendor low
    and best drop source so farm-vs-flip is decidable at a glance. Farmable
    rows also get a model-driven farm z/hr and hours-to-fill this specific
    order, using the same kph derivation as lottery_grinds (curated-spot seed
    first, else the calibrated damage model)."""
    meta_by_id = meta_by_id or {}
    spots = spots or []
    best_drop = _best_drop_sources(drops)

    kph_by_monster: dict[int, int] = {}
    for s in spots:
        per = s["kills_per_hour"] / max(1, len(s["monster_ids"]))
        for mid in s["monster_ids"]:
            kph_by_monster[mid] = max(kph_by_monster.get(mid, 0), round(per))

    agg: dict[int, dict] = {}
    for b in buy_orders:
        r = agg.setdefault(b.item_id, {
            "item_id": b.item_id, "item_name": b.item_name,
            "best_price": 0, "qty_wanted": 0, "orders": 0, "demand_total": 0,
        })
        r["best_price"] = max(r["best_price"], b.price)
        r["qty_wanted"] += b.amount
        r["orders"] += 1
        r["demand_total"] += b.amount * b.price
    rows = []
    for r in agg.values():
        m = markets.get(r["item_id"])
        src = best_drop.get(r["item_id"])
        r["vendor_low"] = m.low if m else None
        r["best_drop_name"] = src[0] if src else None
        r["best_drop_rate"] = src[1] if src else None

        mid = src[2] if src else None
        meta = meta_by_id.get(mid) or {}
        kph = kph_by_monster.get(mid)
        kph_source = "spot" if kph else None
        if not kph and meta.get("hp"):
            kph = model_kills_per_hour(meta["hp"], meta.get("def"), meta.get("size"))
            kph_source = "model"

        r["monster_id"] = mid
        r["rate"] = src[1] if src else None
        r["kph"] = kph
        r["kph_source"] = kph_source
        r["farm_zhr"] = round(src[1] / 100.0 * r["best_price"] * kph) if src and src[1] and kph else None
        r["hours_to_fill"] = round(r["qty_wanted"] / (src[1] / 100.0 * kph), 1) if src and src[1] and kph else None
        rows.append(r)
    rows.sort(key=lambda r: -r["demand_total"])
    return rows


def _build_item_explorer(listings: list, drops: list[dict], buy_orders: list, markets: dict, demand: dict,
                         item_info: dict | None = None):
    item_names: dict[int, str] = {}
    for l in listings:
        item_names.setdefault(l.item_id, l.item_name)
    for d in drops:
        item_names.setdefault(d["item_id"], d["item_name"])
    for b in buy_orders:
        item_names.setdefault(b.item_id, b.item_name)

    item_ids = set(markets.keys()) | {d["item_id"] for d in drops}

    buyer_totals: dict[int, int] = defaultdict(int)
    for b in buy_orders:
        buyer_totals[b.item_id] += b.amount * b.price

    best_drop = _best_drop_sources(drops)

    item_info = item_info or {}
    rows = []
    for item_id in item_ids:
        m = markets.get(item_id)
        src = best_drop.get(item_id)
        info = item_info.get(item_id) or {}
        rows.append(
            {
                "item_id": item_id,
                "item_name": item_names.get(item_id, f"Item #{item_id}"),
                "vendor_low": m.low if m else None,
                "supply": m.supply if m else None,
                "buyer_price": demand.get(item_id),
                "buyer_demand_total": buyer_totals.get(item_id, 0),
                "best_drop_name": src[0] if src else None,
                "best_drop_rate": src[1] if src else None,
                "est_value": _est_value(item_id, markets, demand),
                "desc": info.get("description"),
                "item_type": info.get("item_type"),
                "weight": info.get("weight"),
                "slots": info.get("slots"),
                "atk": info.get("atk"),
                "defense": info.get("defense"),
                "equip_level": info.get("equip_level"),
            }
        )
    rows.sort(key=lambda r: -r["buyer_demand_total"])
    return rows


def _build_exp_planner(turnins: list[dict], markets: dict, char_level: int):
    rows = []
    for r in exp_per_zeny(turnins, markets, char_level):
        rows.append(
            {
                "target_name": r["target_name"],
                "qty": r["qty"],
                "npc": r["npc"],
                "location": r["location"],
                "turnin_cost": r.get("turnin_cost"),
                "base_exp_per_1k_zeny": r.get("base_exp_per_1k_zeny"),
                "note": r.get("note"),
            }
        )
    return rows


def _build_war_chest(war_items: list[dict], stats: dict, history: dict) -> list[dict]:
    """War-supplies watchboard rows: buy-now / realized / velocity from the
    shared item_stats, plus a 7-day price delta from the price-history series
    (first vs last recorded vendor low with >= 2 observed points)."""
    rows = []
    for it in war_items:
        item_id = it["item_id"]
        s = stats.get(item_id, {})
        lows = [p[1] for p in history.get(item_id, []) if p[1] is not None]
        delta7_pct = None
        if len(lows) >= 2 and lows[0]:
            delta7_pct = round((lows[-1] - lows[0]) / lows[0] * 100, 1)
        rows.append(
            {
                "item_id": item_id,
                "item": it["name"],
                "low": s.get("low"),
                "realized_med": s.get("realized_med"),
                "velocity_day": s.get("velocity_day", 0),
                "delta7_pct": delta7_pct,
            }
        )
    return rows


def build_html(
    listings: list,
    buy_orders: list,
    sales: list[dict],
    drops: list[dict],
    spots: list[dict],
    turnins: list[dict],
    char_level: int,
    generated_at: str,
    meta_by_id: dict | None = None,
    best_spawn_by_id: dict | None = None,
    icons: dict | None = None,
    item_info: dict | None = None,
    mob_icons: dict | None = None,
    history: dict | None = None,
    npc_sell: dict | None = None,
    generated_ts: int | None = None,
    merchant_history: list | None = None,
    pnl: dict | None = None,
    balances: list | None = None,
    war_items: list | None = None,
    woe: list | None = None,
) -> str:
    """Pure function: compute every tab's rows from the raw collector data and
    return a complete, self-contained HTML document (no network calls, no I/O)."""
    markets = market_stats(listings, sales, SALES_WINDOW_DAYS)
    demand = demand_map(buy_orders)
    values = value_map(markets, demand)
    demand_ids = set(demand)
    stats = item_stats(listings, sales, buy_orders, npc_sell, SALES_WINDOW_DAYS)
    mm_rows = market_maker(listings, stats)
    corner_rows = corners(listings, stats)

    grind_open, grind_locked = _build_grind_board(
        spots, drops, values, demand_ids, char_level, meta_by_id, best_spawn_by_id)
    lottery_rows = lottery_grinds(drops, markets, demand, spots, meta_by_id, best_spawn_by_id)
    discovered = discover_spots(
        drops, values, demand_ids, meta_by_id or {}, best_spawn_by_id or {},
        {m for s in spots for m in s["monster_ids"]}, char_level)
    flip_rows = flips(listings, buy_orders, markets, npc_sell)
    undercut_rows = undercuts(listings, demand)
    buyer_rows = _build_buyer_orders(buy_orders, drops, markets, meta_by_id, spots)
    items = _build_item_explorer(listings, drops, buy_orders, markets, demand, item_info)
    exp_rows = _build_exp_planner(turnins, markets, char_level)
    merchant_rows = merchant_profiles(merchant_history or [], stats)
    war_rows = _build_war_chest(war_items or [], stats, history or {})

    priced_items = sum(1 for r in items if r["vendor_low"] is not None or r["buyer_price"] is not None)

    data = {
        "generated_at": generated_at,
        "generated_ts": generated_ts,
        "char_level": char_level,
        "summary": {
            "vendor_listings": len(listings),
            "buyer_orders": len(buy_orders),
            "priced_items": priced_items,
        },
        "grind_open": grind_open,
        "grind_locked": grind_locked,
        "discovered": discovered,
        "lotteries": lottery_rows,
        "flips": flip_rows,
        "undercuts": undercut_rows,
        "mm": mm_rows,
        "corners": corner_rows,
        "buyer_orders": buyer_rows,
        "items": items,
        "exp": exp_rows,
        "merchants": merchant_rows,
        "icons": icons or {},
        "pnl": pnl or {},
        "balances": balances or [],
        "war": war_rows,
        "woe": woe or [],
    }

    # Embed only the monster sprites actually referenced by a row.
    used_mobs = ({r["monster_id"] for r in grind_open if r["monster_id"]}
                 | {r["monster_id"] for r in lottery_rows}
                 | {r["monster_id"] for r in discovered})
    data["mob_icons"] = {mid: uri for mid, uri in (mob_icons or {}).items() if mid in used_mobs}

    # Price history (per-day vendor low + best bid) and 7d realized sales, for
    # the Item Explorer detail panel. history_days drives the "collecting -
    # day X of ~7" framing on the not-yet-live signals.
    history = history or {}
    data["history"] = history
    data["history_days"] = len({point[0] for series in history.values() for point in series})
    sales7: dict[int, dict] = {}
    for s_row in sales:
        if s_row["refine"] == 0 and s_row["cards"] == "None":
            agg = sales7.setdefault(s_row["item_id"], {"n": 0, "prices": []})
            agg["n"] += s_row["qty"]
            agg["prices"].append(s_row["price"])
    data["sales7"] = {
        item_id: {"n": a["n"], "med": sorted(a["prices"])[len(a["prices"]) // 2]}
        for item_id, a in sales7.items()
    }

    data_json = json.dumps(data, ensure_ascii=False)
    return _TEMPLATE.replace("__DATA_JSON__", data_json)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RO Economy Command Center</title>
<style>
  /* ============ Frutiger Aero theme system (day: Classic Sky / night: Dawn Aero) ============ */
  body[data-mode="day"] {
    --sky: linear-gradient(170deg, #8fe3ff 0%, #c9f2ff 35%, #f4fdff 70%, #dcf8ce 100%);
    --text: #0b4e74;
    --head: #075a86;
    --muted: #45789b;
    --accent: #1c8fd0;
    --accent-dim: rgba(28, 143, 208, 0.13);
    --panel-bg: rgba(255, 255, 255, 0.62);
    --panel-border: rgba(255, 255, 255, 0.95);
    --panel-shadow: 0 6px 20px rgba(30, 120, 170, 0.18);
    --panel-blur: 6px;
    --thead-bg: rgba(224, 244, 255, 0.9);
    --thead-text: #2b7ba8;
    --row-border: rgba(150, 205, 235, 0.35);
    --row-hover: rgba(160, 225, 255, 0.38);
    --good: #1e7d32;
    --warn: #a86412;
    --danger: #c62839;
    --num: #0d76b4;
    --field-bg: rgba(255, 255, 255, 0.8);
    --field-border: #a9d8ef;
    --tab-active: linear-gradient(#5bc9f2, #1c8fd0);
    --tab-active-text: #ffffff;
    --tab-idle: linear-gradient(rgba(255, 255, 255, 0.95), rgba(220, 240, 250, 0.8));
    --tab-idle-text: #2b7ba8;
    --tab-idle-border: rgba(170, 215, 240, 0.9);
    --strip: linear-gradient(#9be07a, #5cae3a);
    --gloss: 0.55;
    --bubble-op: 0.8;
  }
  body[data-mode="night"] {
    --sky: linear-gradient(165deg, #181c48 0%, #37356f 38%, #7e5da3 68%, #e8956e 94%, #ffd9a0 100%);
    --text: #ffeeda;
    --head: #ffeeda;
    --muted: #cbb9d6;
    --accent: #ffb26b;
    --accent-dim: rgba(255, 178, 107, 0.16);
    --panel-bg: rgba(24, 20, 64, 0.52);
    --panel-border: rgba(255, 220, 190, 0.32);
    --panel-shadow: 0 8px 22px rgba(15, 8, 50, 0.5);
    --panel-blur: 8px;
    --thead-bg: rgba(30, 24, 80, 0.7);
    --thead-text: #d8c2e8;
    --row-border: rgba(255, 220, 190, 0.16);
    --row-hover: rgba(255, 210, 170, 0.13);
    --good: #58e0a5;
    --warn: #ffcf7d;
    --danger: #ff7d92;
    --num: #ffc99a;
    --field-bg: rgba(30, 24, 80, 0.6);
    --field-border: rgba(255, 220, 190, 0.35);
    --tab-active: linear-gradient(#ffd9a8, #e78a4e);
    --tab-active-text: #4a1f05;
    --tab-idle: linear-gradient(rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0.07));
    --tab-idle-text: #ffe9d2;
    --tab-idle-border: rgba(255, 230, 200, 0.32);
    --strip: linear-gradient(90deg, #ff9d6b, #c86bd4, #5a54c9);
    --gloss: 0.35;
    --bubble-op: 0.45;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--sky) fixed;
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    min-height: 100vh;
    transition: color 0.4s;
  }

  /* floating glass bubbles */
  #bubbles { position: fixed; inset: 0; pointer-events: none; z-index: 0; opacity: var(--bubble-op); transition: opacity 0.4s; }
  #bubbles span {
    position: absolute;
    border-radius: 50%;
    background: radial-gradient(circle at 30% 25%, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.08) 55%, rgba(255, 255, 255, 0.18));
    animation: drift 26s ease-in-out infinite alternate;
  }
  #bubbles span:nth-child(1) { width: 120px; height: 120px; right: 6%; top: 12%; }
  #bubbles span:nth-child(2) { width: 46px; height: 46px; right: 16%; top: 34%; animation-duration: 19s; animation-delay: -6s; }
  #bubbles span:nth-child(3) { width: 74px; height: 74px; left: 4%; bottom: 18%; animation-duration: 31s; animation-delay: -12s; }
  #bubbles span:nth-child(4) { width: 26px; height: 26px; left: 14%; top: 22%; animation-duration: 16s; animation-delay: -3s; }
  @keyframes drift {
    from { transform: translate(0, 0); }
    to { transform: translate(-14px, 26px); }
  }

  header, nav.tabs, main, #hero { position: relative; z-index: 1; }

  header { padding: 16px 32px 0; display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
  #generated-at { color: var(--muted); font-size: 0.82rem; margin: 0; }
  .head-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    color: var(--text);
    padding: 5px 13px;
    border-radius: 999px;
    font-size: 0.8rem;
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(4px);
  }
  .chip strong { color: var(--accent); font-weight: 700; }
  #mode-toggle {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    position: relative;
    box-shadow: 0 3px 8px rgba(0, 0, 0, 0.28);
    transition: transform 0.25s;
  }
  #mode-toggle:hover { transform: scale(1.12) rotate(12deg); }
  #mode-toggle::after {
    content: "";
    position: absolute;
    left: 6px; top: 4px;
    width: 18px; height: 10px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.85);
    filter: blur(0.5px);
  }
  body[data-mode="day"] #mode-toggle { background: radial-gradient(circle at 35% 30%, #ffe98a, #f0a72c); }
  body[data-mode="night"] #mode-toggle { background: radial-gradient(circle at 35% 30%, #e8ecff, #8f9bd8); }
  #settings-btn { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--tab-idle-border); background: var(--tab-idle); color: var(--tab-idle-text); cursor: pointer; font-size: 15px; }
  #settings-pop { display: none; position: absolute; right: 32px; top: 60px; z-index: 40; background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 10px; padding: 12px 14px; backdrop-filter: blur(8px); box-shadow: var(--panel-shadow); font-size: 0.85rem; color: var(--text); }
  #settings-pop.open { display: block; }
  #settings-pop input { width: 160px; background: var(--field-bg); border: 1px solid var(--field-border); color: var(--text); border-radius: 6px; padding: 4px 8px; margin-top: 4px; }
  .wl-star { cursor: pointer; color: var(--muted); margin-right: 4px; }
  .wl-star.on { color: var(--warn); }

  /* ============ hero ============ */
  #hero { display: flex; gap: 12px; padding: 12px 32px 4px; flex-wrap: wrap; }
  .glass {
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(var(--panel-blur));
    position: relative;
    overflow: hidden;
    transition: background 0.4s, border-color 0.4s;
  }
  .glass::before {
    content: "";
    position: absolute;
    inset: 0 0 62% 0;
    background: linear-gradient(rgba(255, 255, 255, var(--gloss)), rgba(255, 255, 255, 0));
    border-radius: 14px 14px 45% 45%;
    pointer-events: none;
  }
  .hero-card { padding: 13px 16px; cursor: pointer; min-width: 170px; }
  .hero-card:hover { transform: translateY(-2px); }
  .hero-card, .tab-btn { transition: transform 0.2s, box-shadow 0.2s, background 0.4s, border-color 0.4s; }
  #hero .feat { flex: 1.8; }
  #hero .tile { flex: 1; }
  .hero-k { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.09em; color: var(--muted); position: relative; }
  .hero-v { font-size: 1.45rem; font-weight: 800; color: var(--head); position: relative; line-height: 1.2; }
  .hero-s { font-size: 0.78rem; color: var(--muted); position: relative; }
  .hero-sprite {
    position: absolute;
    right: 12px;
    bottom: 6px;
    max-width: 54px;
    max-height: 54px;
    image-rendering: pixelated;
    filter: drop-shadow(0 3px 4px rgba(0, 0, 0, 0.3));
  }
  .hero-x {
    position: absolute;
    top: 6px;
    right: 8px;
    width: 20px;
    height: 20px;
    border: none;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.14);
    color: var(--muted);
    font-size: 12px;
    line-height: 1;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s;
    z-index: 2;
  }
  .hero-card:hover .hero-x { opacity: 1; }
  .hero-x:hover { background: rgba(0, 0, 0, 0.28); color: #fff; }
  .hero-card.hidden { display: none; }
  #hero-restore {
    display: none;
    align-self: center;
    border: 1px solid var(--tab-idle-border);
    background: var(--tab-idle);
    color: var(--tab-idle-text);
    border-radius: 999px;
    padding: 6px 14px;
    font-size: 0.78rem;
    cursor: pointer;
  }
  #hero-restore.show { display: inline-block; }
  .nw { white-space: nowrap; }
  #goal-wrap { flex-basis: 100%; height: 26px; position: relative; border-radius: 999px; overflow: hidden; }
  #goal-bar { position: absolute; inset: 0; width: 0; background: linear-gradient(90deg, var(--good), var(--accent)); transition: width 1s; }
  #goal-label { position: relative; font-size: 0.75rem; color: var(--head); padding-left: 12px; line-height: 26px; font-weight: 700; }

  /* ============ tabs ============ */
  nav.tabs { display: flex; gap: 8px; padding: 12px 32px 2px; flex-wrap: wrap; border: none; }
  .tab-btn {
    border: 1px solid var(--tab-idle-border);
    background: var(--tab-idle);
    color: var(--tab-idle-text);
    padding: 8px 20px;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    border-radius: 999px;
    position: relative;
    overflow: hidden;
  }
  .tab-btn::before {
    content: "";
    position: absolute;
    inset: 0 0 50% 0;
    background: linear-gradient(rgba(255, 255, 255, 0.75), rgba(255, 255, 255, 0.04));
    pointer-events: none;
  }
  .tab-btn:hover { transform: translateY(-1px); }
  .tab-btn.active {
    background: var(--tab-active);
    color: var(--tab-active-text);
    border-color: transparent;
    box-shadow: 0 3px 9px rgba(0, 0, 0, 0.25);
  }

  main { padding: 18px 32px 40px; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; animation: panelIn 0.24s ease; }
  @keyframes panelIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: none; }
  }

  .panel-card {
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    padding: 18px 20px;
    margin-bottom: 18px;
    box-shadow: var(--panel-shadow);
    backdrop-filter: blur(var(--panel-blur));
    position: relative;
    transition: background 0.4s, border-color 0.4s;
  }
  .panel-card::before {
    content: "";
    position: absolute;
    inset: 0 0 78% 0;
    background: linear-gradient(rgba(255, 255, 255, calc(var(--gloss) * 0.6)), rgba(255, 255, 255, 0));
    border-radius: 14px 14px 0 0;
    pointer-events: none;
  }
  .panel-card h2 { margin: 0 0 12px; font-size: 1.08rem; color: var(--head); position: relative; }
  .panel-card > * { position: relative; }

  input#item-search, input#lot-search {
    width: 100%;
    max-width: 420px;
    background: var(--field-bg);
    border: 1px solid var(--field-border);
    color: var(--text);
    padding: 9px 14px;
    border-radius: 999px;
    font-size: 0.9rem;
    margin-bottom: 14px;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.08);
  }
  input#item-search:focus, input#lot-search:focus { outline: none; border-color: var(--accent); }
  label.check-toggle { display: inline-flex; align-items: center; gap: 8px; color: var(--text); font-size: 0.88rem; margin: 0 0 14px; cursor: pointer; }
  label.check-toggle input[type="checkbox"] { accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }

  table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
  thead th {
    position: sticky;
    top: 0;
    background: var(--thead-bg);
    color: var(--thead-text);
    text-align: left;
    padding: 9px 10px;
    border-bottom: 1px solid var(--row-border);
    cursor: pointer;
    white-space: nowrap;
    user-select: none;
    backdrop-filter: blur(4px);
  }
  thead th:first-child { border-radius: 8px 0 0 0; }
  thead th:last-child { border-radius: 0 8px 0 0; }
  thead th:hover { color: var(--head); }
  thead th.sort-asc::after { content: " \\25B2"; color: var(--accent); }
  thead th.sort-desc::after { content: " \\25BC"; color: var(--accent); }
  tbody td { padding: 8px 10px; border-bottom: 1px solid var(--row-border); vertical-align: top; }
  tbody tr { transition: background 0.15s; }
  tbody tr:hover { background: var(--row-hover); }
  tbody td.empty { text-align: center; color: var(--muted); padding: 18px; }

  .badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.45); }
  body[data-mode="night"] .badge { box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.18); }
  .badge.calibrated { background: rgba(80, 200, 120, 0.22); color: var(--good); }
  .badge.estimated { background: rgba(240, 170, 60, 0.22); color: var(--warn); }
  .badge.normal { background: rgba(80, 200, 120, 0.22); color: var(--good); }
  .badge.miniboss { background: rgba(240, 170, 60, 0.22); color: var(--warn); }
  .badge.mvp { background: rgba(230, 60, 90, 0.2); color: var(--danger); font-weight: 800; letter-spacing: 0.03em; box-shadow: 0 0 0 1px rgba(230, 60, 90, 0.45) inset; }
  .badge.kind-card { background: rgba(150, 100, 240, 0.18); color: var(--accent); }
  body[data-mode="day"] .badge.kind-card { color: #7e22ce; background: rgba(126, 34, 206, 0.12); }
  .badge.kind-gear { background: rgba(70, 150, 240, 0.16); color: #2b7ba8; }
  body[data-mode="night"] .badge.kind-gear { color: #9fd0ff; background: rgba(120, 180, 255, 0.16); }
  .badge.exit-buyer { background: rgba(80, 200, 120, 0.22); color: var(--good); }
  .badge.exit-npc { background: rgba(70, 150, 240, 0.16); color: #2b7ba8; }
  body[data-mode="night"] .badge.exit-npc { color: #9fd0ff; background: rgba(120, 180, 255, 0.16); }

  .drop { color: var(--text); }
  .drop.backed { color: var(--good); }
  .lot { color: var(--warn); }
  .lot.backed { color: var(--good); }
  .check { color: var(--good); font-weight: 700; }
  .col-hint { display: block; font-size: 0.7rem; font-weight: 400; color: var(--muted); text-transform: none; letter-spacing: normal; }
  details.locked-wrap { margin-top: 4px; }
  details.locked-wrap summary { cursor: pointer; color: var(--muted); font-size: 0.9rem; padding: 6px 0; }
  details.locked-wrap summary:hover { color: var(--text); }
  .table-scroll { overflow-x: auto; }

  footer { position: relative; z-index: 1; text-align: center; color: var(--muted); font-size: 0.75rem; padding: 18px 0 26px; }
  #strip { position: relative; z-index: 1; height: 10px; background: var(--strip); box-shadow: inset 0 2px 3px rgba(255, 255, 255, 0.4); }

  .seg { display: inline-flex; gap: 4px; background: var(--field-bg); border: 1px solid var(--field-border); border-radius: 999px; padding: 3px; margin: 0 16px 14px 0; vertical-align: middle; }
  .seg-btn { background: transparent; border: none; color: var(--muted); padding: 5px 15px; border-radius: 999px; font-size: 0.84rem; font-weight: 600; cursor: pointer; }
  .seg-btn:hover { color: var(--text); }
  .seg-btn.active { background: var(--tab-active); color: var(--tab-active-text); box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2); }

  .kpm-edit { cursor: pointer; border-bottom: 1px dashed var(--field-border); }
  .kpm-edit:hover { border-bottom-color: var(--accent); }
  .kpm-input { width: 72px; background: var(--field-bg); border: 1px solid var(--accent); color: var(--text); border-radius: 6px; padding: 2px 6px; font-size: 0.84rem; }

  .item-ic { width: 18px; height: 18px; vertical-align: -4px; margin-right: 6px; image-rendering: pixelated; }
  .mob-ic { max-width: 26px; max-height: 26px; vertical-align: middle; margin-right: 7px; image-rendering: pixelated; filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.25)); }
  .item-cell { cursor: default; }

  /* RO tooltip stays an in-game artifact: dark navy in BOTH modes */
  #item-tooltip {
    position: fixed; display: none; z-index: 50;
    width: 280px;
    background: rgba(7, 14, 38, 0.96);
    border: 1px solid #6a7bb8;
    border-radius: 4px;
    padding: 10px 12px;
    font-size: 0.8rem;
    color: #cdd3ea;
    pointer-events: none;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.55);
  }
  #item-tooltip .tt-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  #item-tooltip .tt-head img { width: 24px; height: 24px; image-rendering: pixelated; }
  #item-tooltip .tt-name { color: #fff; font-weight: 700; }
  #item-tooltip .tt-row { display: flex; justify-content: space-between; gap: 12px; padding: 1px 0; }
  #item-tooltip .tt-row .k { color: #8d96c0; }
  #item-tooltip .tt-backed { color: #34d399; margin-top: 6px; }
  #item-tooltip .tt-facts { color: #a9b2d6; font-size: 0.74rem; margin: -2px 0 6px; }
  #item-tooltip .tt-desc { color: #e6e9f5; margin: 0 0 8px; line-height: 1.35; }
  #item-tooltip .tt-id { color: #8d96c0; font-size: 0.72rem; margin-top: 7px; border-top: 1px solid rgba(106, 123, 184, 0.35); padding-top: 5px; }

  #tab-items tbody tr { cursor: pointer; }
  tr.item-detail td { background: var(--accent-dim); cursor: default; padding: 14px 16px; }
  .detail-wrap { display: flex; gap: 22px; flex-wrap: wrap; align-items: flex-start; }
  .chart-box h3, .signals h3 { margin: 0 0 8px; font-size: 0.85rem; color: var(--head); }
  .chart-legend { display: flex; gap: 14px; margin: 0 0 6px; font-size: 0.76rem; color: var(--muted); }
  .chart-legend .sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
  .chart-empty { color: var(--muted); font-size: 0.82rem; padding: 26px 8px; }
  .signals { min-width: 230px; }
  .sig-card {
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 10px;
    padding: 8px 12px;
    margin-bottom: 8px;
    font-size: 0.8rem;
  }
  .sig-card .k { color: var(--muted); display: block; font-size: 0.72rem; }
  .sig-card .pending { color: var(--warn); }
  #chart-tip {
    position: fixed; display: none; z-index: 60; pointer-events: none;
    background: rgba(7, 14, 38, 0.96); border: 1px solid #6a7bb8; border-radius: 4px;
    padding: 6px 9px; font-size: 0.74rem; color: #cdd3ea;
  }

  /* ============ load-in ============ */
  .rise { opacity: 0; animation: riseIn 0.55s cubic-bezier(0.2, 0.7, 0.3, 1) forwards; }
  .d1 { animation-delay: 0.05s; }
  .d2 { animation-delay: 0.13s; }
  .d3 { animation-delay: 0.21s; }
  .d4 { animation-delay: 0.29s; }
  .d5 { animation-delay: 0.37s; }
  .d6 { animation-delay: 0.45s; }
  @keyframes riseIn {
    from { opacity: 0; transform: translateY(14px); }
    to { opacity: 1; transform: none; }
  }

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; animation-delay: 0s !important; transition-duration: 0.01ms !important; }
    .rise { opacity: 1; }
    #bubbles { display: none; }
  }

</style>
</head>
<body data-mode="day">
<script>
  /* set the mode before first paint: saved choice wins, else by local hour */
  (function () {
    var saved = null;
    try { saved = localStorage.getItem('ro_mode'); } catch (e) {}
    var h = new Date().getHours();
    document.body.dataset.mode = saved || ((h >= 7 && h < 19) ? 'day' : 'night');
  })();
</script>
<div id="bubbles"><span></span><span></span><span></span><span></span></div>

<header class="rise d1">
  <div>
    <p id="generated-at"></p>
  </div>
  <div class="head-right">
    <div class="chips">
      <span class="chip" id="chip-age" title="how old the market snapshot is - flips and snipes decay fast; collect right before a shopping run"></span>
      <span class="chip" id="chip-vendor"></span>
      <span class="chip" id="chip-buyer"></span>
      <span class="chip" id="chip-priced"></span>
      <span class="chip" id="chip-level"></span>
    </div>
    <button id="settings-btn" title="Capital budget and watchlist">&#9881;</button>
    <div id="settings-pop">
      <label>Capital budget (z)<br><input id="capital-input" type="number" min="0" step="100000"></label>
      <div class="col-hint">Used by Corners. Star items (&#9733;) to watch them.</div>
    </div>
    <button id="mode-toggle" title="Toggle day / night mode"></button>
  </div>
</header>

<section id="hero">
  <div class="glass hero-card feat rise d2" id="hero-feat" data-goto="tab-grind"></div>
  <div class="glass hero-card tile rise d3" id="hero-flip" data-goto="tab-flips"></div>
  <div class="glass hero-card tile rise d4" id="hero-snipe" data-goto="tab-snipes"></div>
  <div class="glass hero-card tile rise d5" id="hero-demand" data-goto="tab-buyers"></div>
  <button id="hero-restore" title="Show hidden tiles">+ tiles</button>
  <div id="goal-wrap" class="glass rise d6" style="display: none;"><div id="goal-bar"></div><span id="goal-label"></span></div>
</section>


<nav class="tabs rise d6">
  <button class="tab-btn active" data-tab="tab-grind">Grind Board</button>
  <button class="tab-btn" data-tab="tab-cards">Lotteries</button>
  <button class="tab-btn" data-tab="tab-flips">Flipping</button>
  <button class="tab-btn" data-tab="tab-snipes">Snipes</button>
  <button class="tab-btn" data-tab="tab-mm">Market Maker</button>
  <button class="tab-btn" data-tab="tab-corners">Corners</button>
  <button class="tab-btn" data-tab="tab-items">Item Explorer</button>
  <button class="tab-btn" data-tab="tab-buyers">Buyer Orders</button>
  <button class="tab-btn" data-tab="tab-merch">Merchants</button>
  <button class="tab-btn" data-tab="tab-war">War Chest</button>
  <button class="tab-btn" data-tab="tab-exp">EXP Planner</button>
</nav>

<main>

  <section id="tab-grind" class="tab-panel active">
    <div class="panel-card">
      <h2>Grind Board</h2>
      <div class="table-scroll">
        <table>
          <thead id="grind-open-head">
            <tr>
              <th data-key="rank">Rank</th>
              <th data-key="spot">Spot</th>
              <th data-key="map">Map</th>
              <th data-key="level">Lvl</th>
              <th data-key="hp">HP</th>
              <th data-key="kph">Kills/hr<span class="col-hint">click &middot; enter kills/min</span></th>
              <th data-key="zhr">Reliable z/hr</th>
              <th data-key="calibrated">Confidence</th>
              <th data-key="top_drops">Top Drops<span class="col-hint">reliable</span></th>
              <th data-key="lottery">Lottery<span class="col-hint">card gambles</span></th>
              <th data-key="lottery_ev">Lottery upside<span class="col-hint">card EV z/hr</span></th>
              <th data-key="notes">Notes</th>
            </tr>
          </thead>
          <tbody id="grind-open-body"></tbody>
        </table>
      </div>
    </div>

    <details class="locked-wrap" id="locked-wrap">
      <summary>Locked spots (above your level)</summary>
      <div class="panel-card table-scroll">
        <table>
          <thead id="grind-locked-head">
            <tr>
              <th data-key="spot">Spot</th>
              <th data-key="map">Map</th>
              <th data-key="min_level">Unlocks At</th>
              <th data-key="zhr">z/hr</th>
            </tr>
          </thead>
          <tbody id="grind-locked-body"></tbody>
        </table>
      </div>
    </details>

    <details class="locked-wrap">
      <summary>Discovered spots (model-ranked, all mobs; arrow cost not included)</summary>
      <div class="panel-card table-scroll">
        <table>
          <thead id="disc-head">
            <tr>
              <th data-key="monster">Mob</th><th data-key="map">Map</th>
              <th data-key="level">Lvl</th><th data-key="hp">HP</th>
              <th data-key="kph">Kills/hr<span class="col-hint">click - enter kills/min</span></th>
              <th data-key="zhr">Model z/hr</th><th data-key="exp_hr">Exp/hr</th>
              <th data-key="top_drops">Top Drops</th>
            </tr>
          </thead>
          <tbody id="disc-body"></tbody>
        </table>
      </div>
    </details>
  </section>

  <section id="tab-cards" class="tab-panel">
    <div class="panel-card">
      <h2>Lotteries</h2>
      <input id="lot-search" type="text" placeholder="Search item or monster (e.g. &quot;yao&quot;, &quot;bow&quot;)&hellip;">
      <div class="seg" id="lot-kind-filter">
        <button class="seg-btn active" data-kind="all">All</button>
        <button class="seg-btn" data-kind="card">Cards</button>
        <button class="seg-btn" data-kind="gear">Gear</button>
      </div>
      <label class="check-toggle" for="card-farmable-toggle">
        <input type="checkbox" id="card-farmable-toggle">
        Farmable only <span class="col-hint">hide MVP / mini-boss / no-spawn sources</span>
      </label>
      <div class="table-scroll">
        <table>
          <thead id="card-head">
            <tr>
              <th data-key="item">Item</th>
              <th data-key="kind">Kind</th>
              <th data-key="value">Value (z)</th>
              <th data-key="supply">Supply</th>
              <th data-key="boss_class">Type</th>
              <th data-key="level">Lvl</th>
              <th data-key="hp">HP</th>
              <th data-key="monster">Drops From</th>
              <th data-key="spawn_map">Spawn</th>
              <th data-key="rate">Rate %</th>
              <th data-key="kills_to_first">~Kills</th>
              <th data-key="hours_to_first">~Hours</th>
              <th data-key="backed">Demand</th>
            </tr>
          </thead>
          <tbody id="card-body"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="tab-flips" class="tab-panel">
    <div class="panel-card">
      <h2>Flipping</h2>
      <div class="seg" id="flip-kind-filter">
        <button class="seg-btn active" data-exit="all">All</button>
        <button class="seg-btn" data-exit="buyer">To Buyers</button>
        <button class="seg-btn" data-exit="npc">To NPC (Overcharge)</button>
      </div>
      <div class="table-scroll">
        <table>
          <thead id="flip-head">
            <tr>
              <th data-key="item">Item</th>
              <th data-key="exit">Exit</th>
              <th data-key="vendor_low">Buy At</th>
              <th data-key="exit_price">Sell At</th>
              <th data-key="profit_per">Profit/ea</th>
              <th data-key="qty">Qty</th>
              <th data-key="cost">Cost</th>
              <th data-key="total_profit">Total Profit</th>
              <th data-key="where">Where</th>
            </tr>
          </thead>
          <tbody id="flip-body"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="tab-snipes" class="tab-panel">
    <div class="panel-card">
      <h2>Undercut Snipes</h2>
      <div class="table-scroll">
        <table>
          <thead id="uc-head">
            <tr>
              <th data-key="item">Item</th>
              <th data-key="price">Buy At</th>
              <th data-key="qty">Qty</th>
              <th data-key="cost">Cost</th>
              <th data-key="next_price">Next Ask</th>
              <th data-key="spread">Spread/ea</th>
              <th data-key="potential">Potential</th>
              <th data-key="sellers_above">Sellers @ higher</th>
              <th data-key="backed">Demand</th>
              <th data-key="where">Where</th>
            </tr>
          </thead>
          <tbody id="uc-body"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="tab-mm" class="tab-panel">
    <div class="panel-card">
      <h2>Market Maker</h2>
      <div class="table-scroll"><table>
        <thead id="mm-head"><tr>
          <th data-key="item">Item</th><th data-key="low">Buy From</th>
          <th data-key="cheap_qty">Cheap Qty</th><th data-key="capital">Capital</th>
          <th data-key="realized_med">Sells At<span class="col-hint">realized median</span></th>
          <th data-key="velocity_day">Sold/day</th><th data-key="spread">Spread/ea<span class="col-hint">after tax</span></th>
          <th data-key="profit_day">Est Profit/day</th><th data-key="roi_day">ROI/day</th><th data-key="days_to_turn">Days to Turn</th>
          <th data-key="where">Where</th>
        </tr></thead>
        <tbody id="mm-body"></tbody>
      </table></div>
    </div>
  </section>

  <section id="tab-corners" class="tab-panel">
    <div class="panel-card">
      <h2>Corners</h2>
      <div class="col-hint" style="margin-bottom:12px;">Buying every listing of an item and relisting higher - check server rules, your call. Filtered to your capital budget (gear icon, top right).</div>
      <div class="table-scroll"><table>
        <thead id="corner-head"><tr>
          <th data-key="item">Item</th><th data-key="sellers">Sellers</th>
          <th data-key="qty">Qty</th><th data-key="cost">Cost to Corner</th>
          <th data-key="realized_med">Sells At</th><th data-key="velocity_day">Sold/day</th>
          <th data-key="days_monopoly">Days of Monopoly</th><th data-key="relist">Relist At</th>
          <th data-key="payoff">Est Payoff</th><th data-key="confidence">Confidence</th>
          <th data-key="maps">Maps</th>
        </tr></thead>
        <tbody id="corner-body"></tbody>
      </table></div>
    </div>
  </section>

  <section id="tab-buyers" class="tab-panel">
    <div class="panel-card">
      <h2>Buyer Orders</h2>
      <div class="table-scroll">
        <table>
          <thead id="buyer-head">
            <tr>
              <th data-key="item_name">Item</th>
              <th data-key="best_price">Best Bid</th>
              <th data-key="qty_wanted">Qty Wanted</th>
              <th data-key="orders">Orders</th>
              <th data-key="demand_total">Total Demand (z)</th>
              <th data-key="vendor_low">Vendor Low</th>
              <th data-key="best_drop_rate">Best Drop Source</th>
              <th data-key="farm_zhr">Farm z/hr<span class="col-hint">for this order</span></th>
              <th data-key="hours_to_fill">Hours to fill</th>
            </tr>
          </thead>
          <tbody id="buyer-body"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="tab-merch" class="tab-panel">
    <div class="panel-card">
      <h2>Merchants</h2>
      <div class="col-hint" style="margin-bottom:12px;">Sellers who habitually list below realized value - their shops are a standing snipe subscription. Grows sharper with every daily collect.</div>
      <div class="table-scroll">
        <table>
          <thead id="merch-head">
            <tr>
              <th data-key="merchant">Merchant</th>
              <th data-key="seen">Listings Seen</th>
              <th data-key="items">Items</th>
              <th data-key="hit_rate">Hit Rate</th>
              <th data-key="avg_discount_pct">Avg Discount %</th>
              <th data-key="undercut_value">Undercut Value</th>
              <th data-key="last_seen">Last Seen</th>
              <th data-key="last_where">Last Shop At</th>
            </tr>
          </thead>
          <tbody id="merch-body"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="tab-war" class="tab-panel">
    <div class="panel-card">
      <h2>War Chest</h2>
      <div id="woe-count" class="hero-v" style="margin-bottom:6px;"></div>
      <div class="col-hint" style="margin-bottom:12px;">Day-of-week buy/sell windows activate at 3+ weeks of history - collecting (day <span id="war-days"></span>).</div>
      <div class="table-scroll">
        <table>
          <thead id="war-head">
            <tr>
              <th data-key="item">Item</th>
              <th data-key="low">Buy Now</th>
              <th data-key="realized_med">Realized</th>
              <th data-key="velocity_day">Sold/day</th>
              <th data-key="delta7_pct">7d Price %</th>
            </tr>
          </thead>
          <tbody id="war-body"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="tab-items" class="tab-panel">
    <div class="panel-card">
      <h2>Item Explorer</h2>
      <input id="item-search" type="text" placeholder="Search items (e.g. &quot;card&quot;, &quot;herb&quot;)&hellip;">
      <div class="table-scroll">
        <table>
          <thead id="item-head">
            <tr>
              <th data-key="item_name">Item</th>
              <th data-key="vendor_low">Vendor Low</th>
              <th data-key="supply">Supply</th>
              <th data-key="buyer_price">Buyer Price</th>
              <th data-key="buyer_demand_total">Buyer Demand Total</th>
              <th data-key="best_drop_rate">Best Drop Source</th>
              <th data-key="est_value">Est. Value</th>
            </tr>
          </thead>
          <tbody id="item-body"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="tab-exp" class="tab-panel">
    <div class="panel-card">
      <h2>EXP Planner</h2>
      <div class="table-scroll">
        <table>
          <thead id="exp-head">
            <tr>
              <th data-key="target_name">Item</th>
              <th data-key="qty">Qty</th>
              <th data-key="npc">NPC</th>
              <th data-key="location">Location</th>
              <th data-key="turnin_cost">Cost / Turn-in</th>
              <th data-key="base_exp_per_1k_zeny">Base EXP / 1k z</th>
            </tr>
          </thead>
          <tbody id="exp-body"></tbody>
        </table>
      </div>
    </div>
  </section>

</main>
<div id="item-tooltip"></div>
<div id="chart-tip"></div>
<footer>RO Economy Command Center - generated locally, no data leaves this file.</footer>
<div id="strip"></div>

<script>
const DATA = __DATA_JSON__;

function fmtNum(v) {
  if (v === null || v === undefined) return '-';
  return Math.round(v).toLocaleString('en-US');
}
function fmtPct(v) {
  if (v === null || v === undefined) return '-';
  return v + '%';
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function cmp(a, b) {
  var an = a === null || a === undefined;
  var bn = b === null || b === undefined;
  if (an && bn) return 0;
  if (an) return 1;
  if (bn) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b));
}

function Table(bodyId, columns, rows, defaultKey, defaultDir) {
  this.body = document.getElementById(bodyId);
  this.columns = columns;
  this.allRows = rows;
  this.sortKey = defaultKey;
  this.sortDir = defaultDir;
  this.filterFn = null;
}
Table.prototype.setFilter = function (fn) {
  this.filterFn = fn;
  this.render();
};
Table.prototype.sortBy = function (key) {
  if (this.sortKey === key) {
    this.sortDir *= -1;
  } else {
    var col = this.columns.filter(function (c) { return c.key === key; })[0];
    this.sortKey = key;
    this.sortDir = (col && col.defaultDir) || -1;
  }
  this.updateHeaders();
  this.render();
};
Table.prototype.updateHeaders = function () {
  var thead = this.body.closest('table').querySelector('thead');
  var self = this;
  thead.querySelectorAll('th').forEach(function (th) {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.key === self.sortKey) {
      th.classList.add(self.sortDir === 1 ? 'sort-asc' : 'sort-desc');
    }
  });
};
Table.prototype.render = function () {
  var rows = this.filterFn ? this.allRows.filter(this.filterFn) : this.allRows.slice();
  var col = this.columns.filter(function (c) { return c.key === this.sortKey; }, this)[0];
  var dir = this.sortDir;
  rows = rows.slice().sort(function (a, b) {
    var av = col.get(a), bv = col.get(b);
    var an = av === null || av === undefined, bn = bv === null || bv === undefined;
    if (an && bn) return 0;
    if (an) return 1;
    if (bn) return -1;
    return dir * cmp(av, bv);
  });
  if (!rows.length) {
    this.body.innerHTML = '<tr><td class="empty" colspan="' + this.columns.length + '">No data</td></tr>';
    return;
  }
  var cols = this.columns;
  this.body.innerHTML = rows.map(function (r) {
    return '<tr>' + cols.map(function (c) { return '<td>' + c.render(r) + '</td>'; }).join('') + '</tr>';
  }).join('');
};

function itemCell(id, name) {
  var ic = DATA.icons[id] ? '<img class="item-ic" src="' + DATA.icons[id] + '" alt="">' : '';
  return '<span class="item-cell" data-item="' + id + '">' + ic + esc(name) + '</span>';
}

function mobIcon(mobId) {
  return DATA.mob_icons[mobId] ? '<img class="mob-ic" src="' + DATA.mob_icons[mobId] + '" alt="">' : '';
}

function wireHeaders(theadId, table) {
  document.querySelectorAll('#' + theadId + ' th[data-key]').forEach(function (th) {
    th.addEventListener('click', function () { table.sortBy(th.dataset.key); });
  });
}

var grindOpenCols = [
  { key: 'rank', get: function (r) { return r.rank; }, render: function (r) { return r.rank; }, defaultDir: 1 },
  { key: 'spot', get: function (r) { return r.spot; }, render: function (r) { return '<span class="nw">' + mobIcon(r.monster_id) + esc(r.spot) + '</span>'; }, defaultDir: 1 },
  { key: 'map', get: function (r) { return r.map; }, render: function (r) { return esc(r.map); }, defaultDir: 1 },
  {
    key: 'level',
    get: function (r) { return r.level; },
    render: function (r) { return (r.level === null || r.level === undefined) ? '-' : r.level; },
    defaultDir: -1
  },
  {
    key: 'hp',
    get: function (r) { return r.hp; },
    render: function (r) { return (r.hp === null || r.hp === undefined) ? '-' : fmtNum(r.hp); },
    defaultDir: -1
  },
  {
    key: 'kph',
    get: function (r) { return r.kph; },
    render: function (r) {
      var key = r.monster_id ? ('m' + r.monster_id) : ('s' + r.spot);
      return '<span class="kpm-edit" data-key="' + esc(key) + '" title="click to enter YOUR kills/min ' +
        '- shared with this mob\\u2019s Lotteries rows">' + fmtNum(r.kph) +
        (r.manual ? ' <span class="check">\\u270E</span>' : '') + '</span>';
    },
    defaultDir: -1
  },
  { key: 'zhr', get: function (r) { return r.zhr; }, render: function (r) { return fmtNum(r.zhr); }, defaultDir: -1 },
  {
    key: 'calibrated',
    get: function (r) { return r.calibrated ? 1 : 0; },
    render: function (r) {
      return '<span class="badge ' + (r.calibrated ? 'calibrated' : 'estimated') + '">' +
        (r.calibrated ? 'Calibrated' : 'Estimated') + '</span>';
    },
    defaultDir: -1
  },
  {
    key: 'top_drops',
    get: function (r) { return r.top_drops.map(function (d) { return d.name; }).join(', '); },
    render: function (r) {
      if (!r.top_drops.length) return '-';
      return r.top_drops.map(function (d) {
        return '<span class="drop nw' + (d.backed ? ' backed' : '') + '">' + esc(d.name) + ' (' + fmtNum(d.zhr) + '/hr)</span>';
      }).join('<br>');
    },
    defaultDir: 1
  },
  {
    key: 'lottery',
    get: function (r) { return r.lottery.map(function (c) { return c.name; }).join(', '); },
    render: function (r) {
      if (!r.lottery.length) return '-';
      return r.lottery.map(function (c) {
        var freq = (c.hours_to_first !== null && c.hours_to_first !== undefined)
          ? ('1 per ' + c.hours_to_first + 'h')
          : ('1 per ' + fmtNum(c.kills_to_first) + ' kills');
        return '<span class="lot' + (c.backed ? ' backed' : '') + '">' + esc(c.name) + ' ~' + fmtNum(c.value) + ', ' + freq +
          (c.backed ? ' <span class="check">&#10003;</span>' : '') + '</span>';
      }).join(', ');
    },
    defaultDir: 1
  },
  {
    key: 'lottery_ev',
    get: function (r) { return r.lottery_ev; },
    render: function (r) { return r.lottery_ev ? ('<span class="lot">' + fmtNum(r.lottery_ev) + '/hr</span>') : '-'; },
    defaultDir: -1
  },
  {
    key: 'notes',
    get: function (r) { return r.notes || ''; },
    render: function (r) { return r.notes ? esc(r.notes) : '-'; },
    defaultDir: 1
  }
];

var discCols = [
  { key: 'monster', get: function (r) { return r.monster; }, render: function (r) { return '<span class="nw">' + mobIcon(r.monster_id) + esc(r.monster) + '</span>'; }, defaultDir: 1 },
  { key: 'map', get: function (r) { return r.map; }, render: function (r) { return esc(r.map) + ' (x' + r.density + ')'; }, defaultDir: 1 },
  {
    key: 'level',
    get: function (r) { return r.level; },
    render: function (r) { return (r.level === null || r.level === undefined) ? '-' : r.level; },
    defaultDir: -1
  },
  {
    key: 'hp',
    get: function (r) { return r.hp; },
    render: function (r) { return (r.hp === null || r.hp === undefined) ? '-' : fmtNum(r.hp); },
    defaultDir: -1
  },
  {
    key: 'kph',
    get: function (r) { return r.kph; },
    render: function (r) {
      var key = 'm' + r.monster_id;
      return '<span class="kpm-edit" data-key="' + esc(key) + '" title="click to enter YOUR kills/min">' + fmtNum(r.kph) +
        (r.manual ? ' <span class="check">\\u270E</span>' : '') + '</span>';
    },
    defaultDir: -1
  },
  { key: 'zhr', get: function (r) { return r.zhr; }, render: function (r) { return fmtNum(r.zhr); }, defaultDir: -1 },
  { key: 'exp_hr', get: function (r) { return r.exp_hr; }, render: function (r) { return fmtNum(r.exp_hr); }, defaultDir: -1 },
  {
    key: 'top_drops',
    get: function (r) { return r.top_drops.map(function (d) { return d.name; }).join(', '); },
    render: function (r) {
      if (!r.top_drops.length) return '-';
      return r.top_drops.map(function (d) {
        return '<span class="drop nw' + (d.backed ? ' backed' : '') + '">' + esc(d.name) + ' (' + fmtNum(d.zhr) + '/hr)</span>';
      }).join('<br>');
    },
    defaultDir: 1
  }
];

var buyerCols = [
  { key: 'item_name', get: function (r) { return r.item_name; }, render: function (r) { return itemCell(r.item_id, r.item_name); }, defaultDir: 1 },
  { key: 'best_price', get: function (r) { return r.best_price; }, render: function (r) { return fmtNum(r.best_price); }, defaultDir: -1 },
  { key: 'qty_wanted', get: function (r) { return r.qty_wanted; }, render: function (r) { return fmtNum(r.qty_wanted); }, defaultDir: -1 },
  { key: 'orders', get: function (r) { return r.orders; }, render: function (r) { return r.orders; }, defaultDir: -1 },
  { key: 'demand_total', get: function (r) { return r.demand_total; }, render: function (r) { return fmtNum(r.demand_total); }, defaultDir: -1 },
  { key: 'vendor_low', get: function (r) { return r.vendor_low; }, render: function (r) { return fmtNum(r.vendor_low); }, defaultDir: -1 },
  {
    key: 'best_drop_rate',
    get: function (r) { return r.best_drop_rate; },
    render: function (r) {
      if (!r.best_drop_name) return '-';
      return '<span class="nw">' + mobIcon(r.monster_id) + esc(r.best_drop_name) + ' (' + r.best_drop_rate + '%)</span>';
    },
    defaultDir: -1
  },
  { key: 'farm_zhr', get: function (r) { return r.farm_zhr; },
    render: function (r) {
      if (r.farm_zhr === null || r.farm_zhr === undefined) return '-';
      var key = 'm' + r.monster_id;
      return '<span class="kpm-edit" data-key="' + key + '" title="click to enter YOUR kills/min">' + fmtNum(r.farm_zhr) + (r.kph_source === 'manual' ? ' <span class="check">\\u270E</span>' : (r.kph_source === 'model' ? '*' : '')) + '</span>';
    }, defaultDir: -1 },
  { key: 'hours_to_fill', get: function (r) { return r.hours_to_fill; },
    render: function (r) { return (r.hours_to_fill === null || r.hours_to_fill === undefined) ? '-' : r.hours_to_fill + 'h'; }, defaultDir: 1 }
];

var grindLockedCols = [
  { key: 'spot', get: function (r) { return r.spot; }, render: function (r) { return esc(r.spot); }, defaultDir: 1 },
  { key: 'map', get: function (r) { return r.map; }, render: function (r) { return esc(r.map); }, defaultDir: 1 },
  { key: 'min_level', get: function (r) { return r.min_level; }, render: function (r) { return r.min_level; }, defaultDir: 1 },
  { key: 'zhr', get: function (r) { return r.zhr; }, render: function (r) { return fmtNum(r.zhr); }, defaultDir: -1 }
];

var itemCols = [
  { key: 'item_name', get: function (r) { return r.item_name; }, render: function (r) { return wlStar(r.item_id) + itemCell(r.item_id, r.item_name); }, defaultDir: 1 },
  { key: 'vendor_low', get: function (r) { return r.vendor_low; }, render: function (r) { return fmtNum(r.vendor_low); }, defaultDir: -1 },
  {
    key: 'supply',
    get: function (r) { return r.supply; },
    render: function (r) { return (r.supply === null || r.supply === undefined) ? '-' : r.supply; },
    defaultDir: -1
  },
  { key: 'buyer_price', get: function (r) { return r.buyer_price; }, render: function (r) { return fmtNum(r.buyer_price); }, defaultDir: -1 },
  { key: 'buyer_demand_total', get: function (r) { return r.buyer_demand_total; }, render: function (r) { return fmtNum(r.buyer_demand_total); }, defaultDir: -1 },
  {
    key: 'best_drop_rate',
    get: function (r) { return r.best_drop_rate; },
    render: function (r) { return r.best_drop_name ? (esc(r.best_drop_name) + ' (' + r.best_drop_rate + '%)') : '-'; },
    defaultDir: -1
  },
  { key: 'est_value', get: function (r) { return r.est_value; }, render: function (r) { return fmtNum(r.est_value); }, defaultDir: -1 }
];

var cardCols = [
  { key: 'item', get: function (r) { return r.item; }, render: function (r) { return itemCell(r.item_id, r.item); }, defaultDir: 1 },
  {
    key: 'kind',
    get: function (r) { return r.kind; },
    render: function (r) {
      return '<span class="badge kind-' + r.kind + '">' + (r.kind === 'card' ? 'CARD' : 'GEAR') + '</span>';
    },
    defaultDir: 1
  },
  { key: 'value', get: function (r) { return r.value; }, render: function (r) { return fmtNum(r.value); }, defaultDir: -1 },
  {
    key: 'supply',
    get: function (r) { return r.supply; },
    render: function (r) { return (r.supply === null || r.supply === undefined) ? '-' : fmtNum(r.supply); },
    defaultDir: -1
  },
  {
    key: 'boss_class',
    get: function (r) { return r.boss_class || 'normal'; },
    render: function (r) {
      var bc = r.boss_class || 'normal';
      var label = bc === 'mvp' ? 'MVP' : (bc === 'miniboss' ? 'MINI-BOSS' : 'NORMAL');
      return '<span class="badge ' + bc + '">' + label + '</span>';
    },
    defaultDir: 1
  },
  {
    key: 'level',
    get: function (r) { return r.level; },
    render: function (r) { return (r.level === null || r.level === undefined) ? '-' : r.level; },
    defaultDir: -1
  },
  {
    key: 'hp',
    get: function (r) { return r.hp; },
    render: function (r) { return (r.hp === null || r.hp === undefined) ? '-' : fmtNum(r.hp); },
    defaultDir: -1
  },
  { key: 'monster', get: function (r) { return r.monster; }, render: function (r) { return '<span class="nw">' + mobIcon(r.monster_id) + esc(r.monster) + '</span>'; }, defaultDir: 1 },
  {
    key: 'spawn_map',
    get: function (r) { return r.spawn_map || ''; },
    render: function (r) {
      if (!r.spawn_map) return '-';
      return esc(r.spawn_map) + ' (x' + (r.spawn_density || 0) + ')';
    },
    defaultDir: 1
  },
  { key: 'rate', get: function (r) { return r.rate; }, render: function (r) { return fmtPct(r.rate); }, defaultDir: -1 },
  { key: 'kills_to_first', get: function (r) { return r.kills_to_first; }, render: function (r) { return fmtNum(r.kills_to_first); }, defaultDir: 1 },
  {
    key: 'hours_to_first',
    get: function (r) { return r.hours_to_first; },
    render: function (r) {
      var txt = (r.hours_to_first === null || r.hours_to_first === undefined) ? '-' : r.hours_to_first + 'h';
      var mark = r.kph_source === 'manual' ? ' <span class="check">\\u270E</span>'
        : (r.kph_source === 'model' ? '*' : '');
      var title = (r.kph ? fmtNum(r.kph) + ' kills/hr (' + (r.kph_source || 'seed') + ') - ' : '') +
        'click to enter YOUR kills/min';
      return '<span class="kpm-edit" data-key="m' + r.monster_id + '" title="' + title + '">' + txt + mark + '</span>';
    },
    defaultDir: 1
  },
  {
    key: 'backed',
    get: function (r) { return r.backed ? 1 : 0; },
    render: function (r) { return r.backed ? '<span class="check">&#10003; live buyer</span>' : '-'; },
    defaultDir: -1
  }
];

var flipCols = [
  { key: 'item', get: function (r) { return r.item; }, render: function (r) { return itemCell(r.item_id, r.item); }, defaultDir: 1 },
  {
    key: 'exit',
    get: function (r) { return r.exit; },
    render: function (r) {
      return r.exit === 'npc'
        ? '<span class="badge exit-npc" title="sell to any NPC with Overcharge +24% - unlimited, guaranteed. Still: verify with ONE cheap unit first (undocumented custom prices exist)">NPC</span>'
        : '<span class="badge exit-buyer" title="sell to a standing buy order. RISKS: buy ONLY the Qty shown (that is all the buyer wants), and check the order still exists - it can fill or expire any time after the snapshot">BUYER</span>';
    },
    defaultDir: 1
  },
  { key: 'vendor_low', get: function (r) { return r.vendor_low; }, render: function (r) { return fmtNum(r.vendor_low); }, defaultDir: 1 },
  { key: 'exit_price', get: function (r) { return r.exit_price; }, render: function (r) { return fmtNum(r.exit_price); }, defaultDir: -1 },
  { key: 'profit_per', get: function (r) { return r.profit_per; }, render: function (r) { return fmtNum(r.profit_per); }, defaultDir: -1 },
  {
    key: 'qty',
    get: function (r) { return r.qty; },
    render: function (r) {
      return fmtNum(r.qty) + (r.exit === 'buyer'
        ? ' <span class="col-hint" style="display:inline" title="the buyer wants no more than this - do NOT buy the whole market">max</span>' : '');
    },
    defaultDir: -1
  },
  { key: 'cost', get: function (r) { return r.cost; }, render: function (r) { return fmtNum(r.cost); }, defaultDir: 1 },
  { key: 'total_profit', get: function (r) { return r.total_profit; }, render: function (r) { return fmtNum(r.total_profit); }, defaultDir: -1 },
  {
    key: 'where',
    get: function (r) { return r.where; },
    render: function (r) { return '<span class="nw">' + esc(r.where) + '</span><span class="col-hint">' + esc(r.shop || '') + '</span>'; },
    defaultDir: 1
  }
];

var ucCols = [
  { key: 'item', get: function (r) { return r.item; }, render: function (r) { return itemCell(r.item_id, r.item); }, defaultDir: 1 },
  { key: 'price', get: function (r) { return r.price; }, render: function (r) { return fmtNum(r.price); }, defaultDir: 1 },
  { key: 'qty', get: function (r) { return r.qty; }, render: function (r) { return fmtNum(r.qty); }, defaultDir: -1 },
  { key: 'cost', get: function (r) { return r.cost; }, render: function (r) { return fmtNum(r.cost); }, defaultDir: 1 },
  { key: 'next_price', get: function (r) { return r.next_price; }, render: function (r) { return fmtNum(r.next_price); }, defaultDir: -1 },
  { key: 'spread', get: function (r) { return r.spread; }, render: function (r) { return fmtNum(r.spread); }, defaultDir: -1 },
  { key: 'potential', get: function (r) { return r.potential; }, render: function (r) { return fmtNum(r.potential); }, defaultDir: -1 },
  { key: 'sellers_above', get: function (r) { return r.sellers_above; }, render: function (r) { return r.sellers_above; }, defaultDir: -1 },
  {
    key: 'backed',
    get: function (r) { return r.backed ? 1 : 0; },
    render: function (r) { return r.backed ? '<span class="check">&#10003;</span>' : '-'; },
    defaultDir: -1
  },
  {
    key: 'where',
    get: function (r) { return r.where; },
    render: function (r) { return esc(r.where) + '<span class="col-hint">' + esc(r.shop || '') + '</span>'; },
    defaultDir: 1
  }
];

var mmCols = [
  { key: 'item', get: function (r) { return r.item; }, render: function (r) { return wlStar(r.item_id) + itemCell(r.item_id, r.item); }, defaultDir: 1 },
  { key: 'low', get: function (r) { return r.low; }, render: function (r) { return fmtNum(r.low); }, defaultDir: 1 },
  { key: 'cheap_qty', get: function (r) { return r.cheap_qty; }, render: function (r) { return fmtNum(r.cheap_qty); }, defaultDir: -1 },
  { key: 'capital', get: function (r) { return r.capital; }, render: function (r) { return fmtNum(r.capital); }, defaultDir: 1 },
  { key: 'realized_med', get: function (r) { return r.realized_med; }, render: function (r) { return fmtNum(r.realized_med); }, defaultDir: -1 },
  { key: 'velocity_day', get: function (r) { return r.velocity_day; }, render: function (r) { return r.velocity_day; }, defaultDir: -1 },
  { key: 'spread', get: function (r) { return r.spread; }, render: function (r) { return fmtNum(r.spread); }, defaultDir: -1 },
  { key: 'profit_day', get: function (r) { return r.profit_day; }, render: function (r) { return fmtNum(r.profit_day); }, defaultDir: -1 },
  { key: 'roi_day', get: function (r) { return r.roi_day; }, render: function (r) { return (Math.round(r.roi_day * 1000) / 10) + '%'; }, defaultDir: -1 },
  {
    key: 'days_to_turn',
    get: function (r) { return r.days_to_turn; },
    render: function (r) { return fmtNum(r.days_to_turn) + 'd'; },
    defaultDir: 1
  },
  {
    key: 'where',
    get: function (r) { return r.where; },
    render: function (r) { return '<span class="nw">' + esc(r.where) + '</span><span class="col-hint">' + esc(r.shop || '') + '</span>'; },
    defaultDir: 1
  }
];

var cornerCols = [
  { key: 'item', get: function (r) { return r.item; }, render: function (r) { return wlStar(r.item_id) + itemCell(r.item_id, r.item); }, defaultDir: 1 },
  { key: 'sellers', get: function (r) { return r.sellers; }, render: function (r) { return r.sellers; }, defaultDir: -1 },
  { key: 'qty', get: function (r) { return r.qty; }, render: function (r) { return fmtNum(r.qty); }, defaultDir: -1 },
  { key: 'cost', get: function (r) { return r.cost; }, render: function (r) { return fmtNum(r.cost); }, defaultDir: 1 },
  { key: 'realized_med', get: function (r) { return r.realized_med; }, render: function (r) { return fmtNum(r.realized_med); }, defaultDir: -1 },
  { key: 'velocity_day', get: function (r) { return r.velocity_day; }, render: function (r) { return r.velocity_day; }, defaultDir: -1 },
  {
    key: 'days_monopoly',
    get: function (r) { return r.days_monopoly; },
    render: function (r) { return (r.days_monopoly === null || r.days_monopoly === undefined) ? '-' : r.days_monopoly + 'd'; },
    defaultDir: 1
  },
  { key: 'relist', get: function (r) { return r.relist; }, render: function (r) { return fmtNum(r.relist); }, defaultDir: -1 },
  { key: 'payoff', get: function (r) { return r.payoff; }, render: function (r) { return fmtNum(r.payoff); }, defaultDir: -1 },
  {
    key: 'confidence',
    get: function (r) { return r.confidence; },
    render: function (r) { return '<span class="badge ' + (r.confidence === 'proven' ? 'normal' : 'estimated') + '">' + r.confidence.toUpperCase() + '</span>'; },
    defaultDir: 1
  },
  { key: 'maps', get: function (r) { return r.maps; }, render: function (r) { return esc(r.maps); }, defaultDir: 1 }
];

var merchCols = [
  { key: 'merchant', get: function (r) { return r.merchant; }, render: function (r) { return esc(r.merchant); }, defaultDir: 1 },
  { key: 'seen', get: function (r) { return r.seen; }, render: function (r) { return r.seen; }, defaultDir: -1 },
  { key: 'items', get: function (r) { return r.items; }, render: function (r) { return r.items; }, defaultDir: -1 },
  {
    key: 'hit_rate',
    get: function (r) { return r.hit_rate; },
    render: function (r) { return Math.round(r.hit_rate * 100) + '%'; },
    defaultDir: -1
  },
  {
    key: 'avg_discount_pct',
    get: function (r) { return r.avg_discount_pct; },
    render: function (r) { return r.avg_discount_pct + '%'; },
    defaultDir: -1
  },
  { key: 'undercut_value', get: function (r) { return r.undercut_value; }, render: function (r) { return fmtNum(r.undercut_value); }, defaultDir: -1 },
  { key: 'last_seen', get: function (r) { return r.last_seen; }, render: function (r) { return esc(r.last_seen); }, defaultDir: -1 },
  {
    key: 'last_where',
    get: function (r) { return r.last_where; },
    render: function (r) { return '<span class="nw">' + esc(r.last_where) + '</span>'; },
    defaultDir: 1
  }
];

var warCols = [
  { key: 'item', get: function (r) { return r.item; }, render: function (r) { return wlStar(r.item_id) + itemCell(r.item_id, r.item); }, defaultDir: 1 },
  { key: 'low', get: function (r) { return r.low; }, render: function (r) { return fmtNum(r.low); }, defaultDir: -1 },
  { key: 'realized_med', get: function (r) { return r.realized_med; }, render: function (r) { return fmtNum(r.realized_med); }, defaultDir: -1 },
  { key: 'velocity_day', get: function (r) { return r.velocity_day; }, render: function (r) { return r.velocity_day; }, defaultDir: -1 },
  {
    key: 'delta7_pct',
    get: function (r) { return r.delta7_pct; },
    render: function (r) {
      return (r.delta7_pct === null || r.delta7_pct === undefined) ? '-' : (r.delta7_pct > 0 ? '+' : '') + r.delta7_pct + '%';
    },
    defaultDir: -1
  }
];

var expCols = [
  { key: 'target_name', get: function (r) { return r.target_name; }, render: function (r) { return esc(r.target_name); }, defaultDir: 1 },
  { key: 'qty', get: function (r) { return r.qty; }, render: function (r) { return fmtNum(r.qty); }, defaultDir: -1 },
  { key: 'npc', get: function (r) { return r.npc; }, render: function (r) { return esc(r.npc); }, defaultDir: 1 },
  { key: 'location', get: function (r) { return r.location; }, render: function (r) { return esc(r.location); }, defaultDir: 1 },
  {
    key: 'turnin_cost',
    get: function (r) { return r.turnin_cost; },
    render: function (r) {
      if (r.turnin_cost !== null && r.turnin_cost !== undefined) return fmtNum(r.turnin_cost);
      return r.note ? esc(r.note) : '-';
    },
    defaultDir: -1
  },
  { key: 'base_exp_per_1k_zeny', get: function (r) { return r.base_exp_per_1k_zeny; }, render: function (r) { return fmtNum(r.base_exp_per_1k_zeny); }, defaultDir: -1 }
];

var grindOpenTable = new Table('grind-open-body', grindOpenCols, DATA.grind_open, 'zhr', -1);
var grindLockedTable = new Table('grind-locked-body', grindLockedCols, DATA.grind_locked, 'zhr', -1);
var discTable = new Table('disc-body', discCols, DATA.discovered, 'zhr', -1);
var cardTable = new Table('card-body', cardCols, DATA.lotteries, 'value', -1);
var flipTable = new Table('flip-body', flipCols, DATA.flips, 'total_profit', -1);
var ucTable = new Table('uc-body', ucCols, DATA.undercuts, 'potential', -1);
var mmTable = new Table('mm-body', mmCols, DATA.mm, 'profit_day', -1);
var cornerAll = DATA.corners;
var cornerTable = new Table('corner-body', cornerCols, cornerAll, 'payoff', -1);
var buyerTable = new Table('buyer-body', buyerCols, DATA.buyer_orders, 'farm_zhr', -1);
var itemTable = new Table('item-body', itemCols, DATA.items, 'buyer_demand_total', -1);
var expTable = new Table('exp-body', expCols, DATA.exp, 'base_exp_per_1k_zeny', -1);
var merchTable = new Table('merch-body', merchCols, DATA.merchants, 'undercut_value', -1);
var warTable = new Table('war-body', warCols, DATA.war, 'velocity_day', -1);

wireHeaders('grind-open-head', grindOpenTable);
wireHeaders('grind-locked-head', grindLockedTable);
wireHeaders('disc-head', discTable);
wireHeaders('card-head', cardTable);
wireHeaders('flip-head', flipTable);
wireHeaders('uc-head', ucTable);
wireHeaders('mm-head', mmTable);
wireHeaders('corner-head', cornerTable);
wireHeaders('buyer-head', buyerTable);
wireHeaders('item-head', itemTable);
wireHeaders('exp-head', expTable);
wireHeaders('merch-head', merchTable);
wireHeaders('war-head', warTable);

// --- kills/min manual overrides (persisted in this browser) ---
// Click a Reliable-z/hr cell (Grind Board) or an ~Hours cell (Lotteries),
// type your observed kills/min, Enter. Numbers rescale; \\u270E marks manual.
var KPM_KEY = 'ro_kpm_v1';
function loadKpm() {
  try { return JSON.parse(localStorage.getItem(KPM_KEY)) || {}; } catch (e) { return {}; }
}
function saveKpm(map) {
  try { localStorage.setItem(KPM_KEY, JSON.stringify(map)); } catch (e) {}
}
function applyOverrides() {
  var map = loadKpm();
  DATA.lotteries.forEach(function (r) {
    if (r._kph0 === undefined) { r._kph0 = r.kph; r._src0 = r.kph_source; }
    var ov = map['m' + r.monster_id];
    if (ov) {
      r.kph = Math.round(ov * 60);
      r.kph_source = 'manual';
    } else {
      r.kph = r._kph0;
      r.kph_source = r._src0;
    }
    r.hours_to_first = r.kph ? Math.round(r.kills_to_first / r.kph * 10) / 10 : null;
  });
  DATA.grind_open.forEach(function (r) {
    if (r._zhr0 === undefined) { r._zhr0 = r.zhr; r._lot0 = r.lottery_ev; r._kph0 = r.kph; }
    // per-MONSTER override (shared with Lotteries); legacy per-spot key still honored
    var ov = (r.monster_id && map['m' + r.monster_id]) || map['s' + r.spot];
    if (ov && r._kph0) {
      var ratio = (ov * 60) / r._kph0;
      r.kph = Math.round(ov * 60);
      r.zhr = Math.round((r._zhr0 + r.arrow_cost) * ratio - r.arrow_cost);
      r.lottery_ev = Math.round(r._lot0 * ratio);
      r.manual = true;
    } else {
      r.kph = r._kph0;
      r.zhr = r._zhr0;
      r.lottery_ev = r._lot0;
      r.manual = false;
    }
  });
  DATA.buyer_orders.forEach(function (r) {
    if (!r.monster_id) return;
    if (r._kph0 === undefined) { r._kph0 = r.kph; r._src0 = r.kph_source; }
    var ov = map['m' + r.monster_id];
    if (ov) { r.kph = Math.round(ov * 60); r.kph_source = 'manual'; }
    else { r.kph = r._kph0; r.kph_source = r._src0; }
    r.farm_zhr = (r.kph && r.rate) ? Math.round(r.rate / 100 * r.best_price * r.kph) : null;
    r.hours_to_fill = (r.kph && r.rate) ? Math.round(r.qty_wanted / (r.rate / 100 * r.kph) * 10) / 10 : null;
  });
  DATA.discovered.forEach(function (r) {
    if (r._kph0 === undefined) { r._kph0 = r.kph; r._zhr0 = r.zhr; r._exp0 = r.exp_hr; }
    var ov = map['m' + r.monster_id];
    if (ov && r._kph0) {
      r.kph = Math.round(ov * 60);
      r.zhr = Math.round(r._zhr0 * r.kph / r._kph0);
      r.exp_hr = Math.round(r._exp0 * r.kph / r._kph0);
      r.manual = true;
    } else { r.kph = r._kph0; r.zhr = r._zhr0; r.exp_hr = r._exp0; r.manual = false; }
  });
}
function rerenderKpmTables() {
  applyOverrides();
  grindOpenTable.render();
  cardTable.render();
  buyerTable.render();
  discTable.render();
  fillHero(false);
}
document.querySelector('main').addEventListener('click', function (ev) {
  var el = ev.target.closest ? ev.target.closest('.kpm-edit') : null;
  if (!el || el.querySelector('input')) return;
  var key = el.dataset.key;
  var cur = loadKpm()[key] || '';
  el.innerHTML = '<input class="kpm-input" type="number" min="0" step="0.1" value="' + cur + '" placeholder="kills/min">';
  var inp = el.querySelector('input');
  inp.focus();
  inp.select();
  var done = false;
  function commit() {
    if (done) return;
    done = true;
    var v = parseFloat(inp.value);
    var m = loadKpm();
    if (v > 0) { m[key] = v; } else { delete m[key]; }  // empty or 0 clears the override
    saveKpm(m);
    rerenderKpmTables();
  }
  inp.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') commit();
    if (e.key === 'Escape') { done = true; rerenderKpmTables(); }
  });
  inp.addEventListener('blur', commit);
});

// --- RO-style item tooltip (hover any item name) ---
var ITEM_INFO = {};
DATA.items.forEach(function (r) { ITEM_INFO[r.item_id] = r; });
var tipEl = document.getElementById('item-tooltip');
function ttRow(k, v) {
  return '<div class="tt-row"><span class="k">' + k + '</span><span>' + v + '</span></div>';
}
function fmtZ(v) { return (v === null || v === undefined) ? '-' : fmtNum(v) + ' z'; }
function positionTip(ev) {
  var pad = 14;
  var w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  var x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > window.innerWidth - 8) x = ev.clientX - w - pad;
  if (y + h > window.innerHeight - 8) y = ev.clientY - h - pad;
  tipEl.style.left = x + 'px';
  tipEl.style.top = y + 'px';
}
function roDesc(text) {
  // RO color codes: ^RRGGBB switches text color until the next code.
  // Very dark codes are unreadable on the navy tooltip -> default color.
  var parts = String(text).split(/\\^([0-9a-fA-F]{6})/);
  var html = esc(parts[0]).replace(/\\n/g, '<br>');
  for (var i = 1; i < parts.length; i += 2) {
    var c = parts[i].toLowerCase();
    var dark = parseInt(c, 16) < 0x404040;
    html += '<span style="color:' + (dark ? '#cdd3ea' : '#' + c) + '">' +
      esc(parts[i + 1] || '').replace(/\\n/g, '<br>') + '</span>';
  }
  return html;
}
document.addEventListener('mouseover', function (ev) {
  var el = ev.target.closest ? ev.target.closest('.item-cell') : null;
  if (!el) { tipEl.style.display = 'none'; return; }
  var id = el.dataset.item;
  var info = ITEM_INFO[id];
  var name = el.textContent;
  var ic = DATA.icons[id] ? '<img src="' + DATA.icons[id] + '" alt="">' : '';
  var html = '<div class="tt-head">' + ic + '<span class="tt-name">' + esc(name) + '</span></div>';
  if (info) {
    var facts = [];
    if (info.item_type) facts.push(esc(info.item_type));
    if (info.atk) facts.push('ATK ' + info.atk);
    if (info.defense) facts.push('DEF ' + info.defense);
    if (info.slots) facts.push(info.slots + ' slot' + (info.slots > 1 ? 's' : ''));
    if (info.weight) facts.push('Weight ' + info.weight);
    if (info.equip_level) facts.push('Lv ' + info.equip_level + '+');
    if (facts.length) html += '<div class="tt-facts">' + facts.join(' \\u00B7 ') + '</div>';
    if (info.desc) html += '<div class="tt-desc">' + roDesc(info.desc) + '</div>';
    html += ttRow('Est. value', fmtZ(info.est_value));
    if (info.best_drop_name) {
      html += ttRow('Best source', esc(info.best_drop_name) + ' (' + info.best_drop_rate + '%)');
    }
    if (info.buyer_price) {
      html += '<div class="tt-backed">\\u2713 live buyer order - sells right now</div>';
    }
  } else {
    html += '<div class="tt-row"><span class="k">no data</span></div>';
  }
  html += '<div class="tt-id">ID ' + id + '</div>';
  tipEl.innerHTML = html;
  tipEl.style.display = 'block';
  positionTip(ev);
});
document.addEventListener('mousemove', function (ev) {
  if (tipEl.style.display === 'block') positionTip(ev);
});

// --- Item Explorer detail panel: price history chart + market signals ---
// Series colors validated per surface (dataviz validator): day pair on
// #e8f6fd, night pair on #2a2456 - lightness/chroma/CVD/contrast all pass.
function chartColors() {
  return document.body.dataset.mode === 'day'
    ? { low: '#7e22ce', bid: '#047857', grid: 'rgba(11,78,116,.18)', label: '#45789b', ring: '#eef8ff' }
    : { low: '#a855f7', bid: '#059669', grid: 'rgba(255,238,218,.18)', label: '#cbb9d6', ring: '#2a2456' };
}
function zShort(v) {
  if (v >= 1e6) return (Math.round(v / 1e5) / 10) + 'M';
  if (v >= 1e3) return (Math.round(v / 100) / 10) + 'k';
  return String(v);
}
function drawChart(hist) {
  var CC = chartColors();
  var W = 560, H = 170, L = 52, R = 14, T = 10, B = 22;
  var vals = [];
  hist.forEach(function (p) { if (p[1] != null) vals.push(p[1]); if (p[2] != null) vals.push(p[2]); });
  if (!vals.length) return '<div class="chart-empty">No price points yet.</div>';
  var ymax = Math.max.apply(null, vals) * 1.15 || 1;
  var n = hist.length;
  var x = function (i) { return n === 1 ? (L + (W - L - R) / 2) : L + (W - L - R) * i / (n - 1); };
  var y = function (v) { return T + (H - T - B) * (1 - v / ymax); };
  var svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img">';
  for (var g = 1; g <= 3; g++) {
    var gv = ymax * g / 4, gy = y(gv);
    svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + gy + '" y2="' + gy + '" stroke="' + CC.grid + '" stroke-width="1"/>';
    svg += '<text x="' + (L - 6) + '" y="' + (gy + 3) + '" text-anchor="end" font-size="10" fill="' + CC.label + '">' + zShort(gv) + '</text>';
  }
  svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="' + CC.grid + '" stroke-width="1"/>';
  ['low', 'bid'].forEach(function (key, si) {
    var c = CC[key];
    var path = '', pen = false;
    hist.forEach(function (p, i) {
      var v = p[si + 1];
      if (v == null) { pen = false; return; }
      path += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1) + ' ';
      pen = true;
    });
    if (path) svg += '<path d="' + path + '" fill="none" stroke="' + c + '" stroke-width="2"/>';
    hist.forEach(function (p, i) {
      var v = p[si + 1];
      if (v == null) return;
      svg += '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(v).toFixed(1) + '" r="4" fill="' + c +
        '" stroke="' + CC.ring + '" stroke-width="2" class="ch-pt" data-d="' + p[0] + '" data-v="' + v +
        '" data-s="' + (si ? 'Buyer bid' : 'Vendor low') + '"/>';
    });
  });
  hist.forEach(function (p, i) {
    if (n <= 10 || i === 0 || i === n - 1 || i % Math.ceil(n / 6) === 0) {
      svg += '<text x="' + x(i).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="10" fill="' + CC.label + '">' + p[0].slice(5) + '</text>';
    }
  });
  return svg + '</svg>';
}
function sigCard(label, value, pending) {
  return '<div class="sig-card"><span class="k">' + label + '</span>' +
    (pending ? '<span class="pending">' + value + '</span>' : value) + '</div>';
}
function detailPanel(id) {
  var hist = DATA.history[id] || [];
  var s7 = DATA.sales7[id];
  var pendingNote = 'collecting history - day ' + DATA.history_days + ' of ~7';
  var chart = hist.length
    ? drawChart(hist)
    : '<div class="chart-empty">No snapshots with this item yet.</div>';
  var legend = '<div class="chart-legend">' +
    '<span><span class="sw" style="background:' + chartColors().low + '"></span>Vendor low</span>' +
    '<span><span class="sw" style="background:' + chartColors().bid + '"></span>Buyer bid</span></div>';
  var sig = '<div class="signals"><h3>Market signals</h3>' +
    sigCard('Realized sales (7d)', s7 ? (fmtNum(s7.n) + ' sold \\u00B7 median ' + fmtNum(s7.med) + ' z') : 'none observed yet', !s7) +
    sigCard('Sell-through / day', s7 ? '~' + (Math.round(s7.n / Math.max(1, DATA.history_days) * 10) / 10) + ' / day' : pendingNote, !s7) +
    sigCard('Flip prediction', pendingNote, true) +
    '</div>';
  return '<div class="detail-wrap"><div class="chart-box"><h3>Price history</h3>' + legend + chart + '</div>' + sig + '</div>';
}
document.getElementById('item-body').addEventListener('click', function (ev) {
  if (ev.target.closest && (ev.target.closest('input') || ev.target.closest('.wl-star'))) return;
  var tr = ev.target.closest ? ev.target.closest('tr') : null;
  if (!tr || tr.classList.contains('item-detail')) return;
  var cell = tr.querySelector('.item-cell');
  if (!cell) return;
  var wasOpen = tr.nextElementSibling && tr.nextElementSibling.classList.contains('item-detail');
  document.querySelectorAll('tr.item-detail').forEach(function (d) { d.remove(); });
  if (wasOpen) return;
  var d = document.createElement('tr');
  d.className = 'item-detail';
  d.innerHTML = '<td colspan="' + tr.children.length + '">' + detailPanel(cell.dataset.item) + '</td>';
  tr.parentNode.insertBefore(d, tr.nextSibling);
});
var chartTip = document.getElementById('chart-tip');
document.addEventListener('mouseover', function (ev) {
  var pt = ev.target.classList && ev.target.classList.contains('ch-pt') ? ev.target : null;
  if (!pt) { chartTip.style.display = 'none'; return; }
  chartTip.innerHTML = esc(pt.dataset.s) + ' \\u00B7 ' + esc(pt.dataset.d) + '<br><strong>' + fmtNum(+pt.dataset.v) + ' z</strong>';
  chartTip.style.display = 'block';
  chartTip.style.left = (ev.clientX + 12) + 'px';
  chartTip.style.top = (ev.clientY - 34) + 'px';
});

// --- day/night mode toggle ---
document.getElementById('mode-toggle').addEventListener('click', function () {
  var next = document.body.dataset.mode === 'day' ? 'night' : 'day';
  document.body.dataset.mode = next;
  try { localStorage.setItem('ro_mode', next); } catch (e) {}
  // charts bake their colors at draw time - close open detail panels so the
  // next open redraws in the right palette
  document.querySelectorAll('tr.item-detail').forEach(function (d) { d.remove(); });
});

// --- hero: featured spot + stat tiles, derived from DATA (override-aware) ---
var REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function countUp(el, target) {
  if (REDUCED || !target) { el.textContent = fmtNum(target); return; }
  var t0 = null;
  function step(ts) {
    if (!t0) t0 = ts;
    var k = Math.min(1, (ts - t0) / 800);
    k = 1 - Math.pow(1 - k, 3);
    el.textContent = fmtNum(Math.round(target * k));
    if (k < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
function heroX() { return '<button class="hero-x" title="Hide this tile">\\u00D7</button>'; }
function fillHero(animate) {
  var feat = document.getElementById('hero-feat');
  var top = DATA.grind_open.slice().sort(function (a, b) { return b.zhr - a.zhr; })[0];
  if (top) {
    var bits = [];
    if (top.map) bits.push(esc(top.map));
    if (top.notes) bits.push(esc(top.notes.split(' \\u00B7 ')[0]));
    feat.innerHTML = '<span class="hero-k">Farm tonight</span>' +
      '<div class="hero-v">' + esc(top.spot) + ' \\u00B7 <span id="hero-feat-n"></span> z/hr</div>' +
      '<div class="hero-s">' + bits.join(' \\u00B7 ') + (top.manual ? ' \\u00B7 \\u270E your kills/min' : '') + '</div>' +
      (DATA.mob_icons[top.monster_id] ? '<img class="hero-sprite" src="' + DATA.mob_icons[top.monster_id] + '" alt="">' : '');
    countUp(document.getElementById('hero-feat-n'), top.zhr);
  } else {
    feat.innerHTML = '<span class="hero-k">Farm tonight</span><div class="hero-v">-</div>';
  }
  var flip = DATA.flips[0];
  document.getElementById('hero-flip').innerHTML = '<span class="hero-k">Best flip</span>' +
    (flip ? '<div class="hero-v"><span id="hero-flip-n"></span> z</div><div class="hero-s">' + esc(flip.item) + ' \\u00D7' + fmtNum(flip.qty) + '</div>'
          : '<div class="hero-v">-</div><div class="hero-s">no arbitrage right now</div>');
  if (flip) countUp(document.getElementById('hero-flip-n'), flip.total_profit);
  var uc = DATA.undercuts[0];
  document.getElementById('hero-snipe').innerHTML = '<span class="hero-k">Top snipe</span>' +
    (uc ? '<div class="hero-v"><span id="hero-snipe-n"></span> z</div><div class="hero-s">' + esc(uc.item) + ' @ ' + esc(uc.where) + '</div>'
        : '<div class="hero-v">-</div><div class="hero-s">no undercuts right now</div>');
  if (uc) countUp(document.getElementById('hero-snipe-n'), uc.potential);
  var demandTotal = 0;
  DATA.buyer_orders.forEach(function (r) { demandTotal += r.demand_total; });
  document.getElementById('hero-demand').innerHTML = '<span class="hero-k">Buyer demand</span>' +
    '<div class="hero-v"><span id="hero-demand-n"></span> z</div>' +
    '<div class="hero-s">' + fmtNum(DATA.buyer_orders.length) + ' items wanted</div>';
  countUp(document.getElementById('hero-demand-n'), demandTotal);
  document.querySelectorAll('#hero .hero-card').forEach(function (c) { c.insertAdjacentHTML('beforeend', heroX()); });
}

// --- 1B-zeny goal bar, driven by the latest logged balance ---
function buildGoalBar() {
  var wrap = document.getElementById('goal-wrap');
  var bal = DATA.balances.length ? DATA.balances[DATA.balances.length - 1][1] : null;
  if (bal === null || bal === undefined) { wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  document.getElementById('goal-bar').style.width = Math.min(100, bal / 1e9 * 100) + '%';
  document.getElementById('goal-label').textContent =
    fmtNum(bal) + ' / 1B z (' + (bal / 1e7).toFixed(1) + '%)';
}


// --- hero tile hide/restore (persisted) ---
var HERO_KEY = 'ro_hero_hidden';
function heroHidden() {
  try { return JSON.parse(localStorage.getItem(HERO_KEY)) || []; } catch (e) { return []; }
}
function applyHeroHidden() {
  var hidden = heroHidden();
  document.querySelectorAll('#hero .hero-card').forEach(function (c) {
    c.classList.toggle('hidden', hidden.indexOf(c.id) !== -1);
  });
  document.getElementById('hero-restore').classList.toggle('show', hidden.length > 0);
}
document.getElementById('hero-restore').addEventListener('click', function () {
  try { localStorage.removeItem(HERO_KEY); } catch (e) {}
  applyHeroHidden();
});
document.getElementById('hero').addEventListener('click', function (ev) {
  var x = ev.target.closest ? ev.target.closest('.hero-x') : null;
  if (x) {
    ev.stopPropagation();
    var card = x.closest('.hero-card');
    var hidden = heroHidden();
    if (hidden.indexOf(card.id) === -1) hidden.push(card.id);
    try { localStorage.setItem(HERO_KEY, JSON.stringify(hidden)); } catch (e) {}
    applyHeroHidden();
    return;
  }
  var card2 = ev.target.closest ? ev.target.closest('.hero-card') : null;
  if (!card2 || !card2.dataset.goto) return;
  var btn = document.querySelector('.tab-btn[data-tab="' + card2.dataset.goto + '"]');
  if (btn) btn.click();
});

var SETTINGS_KEY = 'ro_settings_v1';
function getSettings() {
  try { return Object.assign({capital: 10000000, watch: []}, JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}); }
  catch (e) { return {capital: 10000000, watch: []}; }
}
function saveSettings(s) {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); } catch (e) {}
  window.dispatchEvent(new Event('ro-settings'));
}
function wlStar(itemId) {
  var on = getSettings().watch.indexOf(Number(itemId)) !== -1;
  return '<span class="wl-star' + (on ? ' on' : '') + '" data-item="' + itemId + '" title="watchlist">' + (on ? '★' : '☆') + '</span>';
}
document.addEventListener('click', function (ev) {
  var star = ev.target.closest ? ev.target.closest('.wl-star') : null;
  if (star) {
    ev.stopPropagation();
    var s = getSettings(); var id = Number(star.dataset.item);
    var i = s.watch.indexOf(id);
    if (i === -1) s.watch.push(id); else s.watch.splice(i, 1);
    saveSettings(s);
    star.classList.toggle('on', i === -1);
    star.textContent = i === -1 ? '★' : '☆';
    return;
  }
  var pop = document.getElementById('settings-pop');
  if (ev.target.closest && ev.target.closest('#settings-btn')) { pop.classList.toggle('open'); return; }
  if (!ev.target.closest || !ev.target.closest('#settings-pop')) pop.classList.remove('open');
});
document.getElementById('capital-input').value = getSettings().capital;
document.getElementById('capital-input').addEventListener('change', function (e) {
  var s = getSettings(); s.capital = Math.max(0, parseInt(e.target.value || '0', 10)); saveSettings(s);
});

applyOverrides();
[grindOpenTable, grindLockedTable, discTable, cardTable, flipTable, ucTable, mmTable, cornerTable, buyerTable, itemTable, expTable, merchTable, warTable].forEach(function (t) {
  t.updateHeaders();
  t.render();
});
fillHero(true);
applyHeroHidden();
cornerFilter();
buildGoalBar();

if (!DATA.grind_locked.length) {
  var lockedWrap = document.getElementById('locked-wrap');
  if (lockedWrap) lockedWrap.style.display = 'none';
}

document.getElementById('item-search').addEventListener('input', function (e) {
  var q = e.target.value.trim().toLowerCase();
  itemTable.setFilter(q ? function (r) { return r.item_name.toLowerCase().indexOf(q) !== -1; } : null);
});

var lotKind = 'all';
var lotFarmableOnly = false;
var lotQuery = '';
function applyLotFilter() {
  if (lotKind === 'all' && !lotFarmableOnly && !lotQuery) { cardTable.setFilter(null); return; }
  cardTable.setFilter(function (r) {
    if (lotKind !== 'all' && r.kind !== lotKind) return false;
    if (lotFarmableOnly && r.farmable !== true) return false;
    if (lotQuery && r.item.toLowerCase().indexOf(lotQuery) === -1 &&
        (r.monster || '').toLowerCase().indexOf(lotQuery) === -1) return false;
    return true;
  });
}
document.getElementById('lot-search').addEventListener('input', function (e) {
  lotQuery = e.target.value.trim().toLowerCase();
  applyLotFilter();
});

document.querySelectorAll('#flip-kind-filter .seg-btn').forEach(function (btn) {
  btn.addEventListener('click', function () {
    document.querySelectorAll('#flip-kind-filter .seg-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    var kind = btn.dataset.exit;
    flipTable.setFilter(kind === 'all' ? null : function (r) { return r.exit === kind; });
  });
});

function cornerFilter() {
  var cap = getSettings().capital;
  cornerTable.allRows = cornerAll.filter(function (r) { return r.cost <= cap; });
  cornerTable.render();
}
window.addEventListener('ro-settings', cornerFilter);

document.getElementById('card-farmable-toggle').addEventListener('change', function (e) {
  lotFarmableOnly = e.target.checked;
  applyLotFilter();
});
document.querySelectorAll('#lot-kind-filter .seg-btn').forEach(function (btn) {
  btn.addEventListener('click', function () {
    document.querySelectorAll('#lot-kind-filter .seg-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    lotKind = btn.dataset.kind;
    applyLotFilter();
  });
});

document.querySelectorAll('.tab-btn').forEach(function (btn) {
  btn.addEventListener('click', function () {
    document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
    document.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});

document.getElementById('generated-at').textContent = 'Generated ' + DATA.generated_at;
(function () {
  var chip = document.getElementById('chip-age');
  if (!DATA.generated_ts) { chip.style.display = 'none'; return; }
  function renderAge() {
    var h = (Date.now() / 1000 - DATA.generated_ts) / 3600;
    var txt = h < 1 ? Math.max(1, Math.round(h * 60)) + 'm' : (Math.round(h * 10) / 10) + 'h';
    var warn = h >= 8;
    chip.innerHTML = 'snapshot <strong style="color:' + (warn ? 'var(--danger)' : 'var(--good)') + '">' +
      txt + ' old</strong>';
  }
  renderAge();
  setInterval(renderAge, 60000);
})();

// --- WoE countdown: schedule is UTC (server time) -- must use UTC getters,
// never local-time ones, or the countdown drifts by the viewer's timezone.
(function () {
  var el = document.getElementById('woe-count');
  if (!el) return;
  if (!DATA.woe || !DATA.woe.length) { el.textContent = '-'; return; }
  function renderCountdown() {
    var now = new Date();
    var nowMs = now.getTime();
    var best = null;
    for (var d = 0; d <= 7; d++) {
      var day = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + d));
      DATA.woe.forEach(function (w) {
        if (day.getUTCDay() !== w.weekday) return;
        var startMs = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), w.start_hh, w.start_mm, 0);
        var endMs = startMs + w.duration_min * 60000;
        if (endMs < nowMs) return; // this occurrence already fully elapsed
        if (best === null || startMs < best.startMs) best = { startMs: startMs, endMs: endMs };
      });
    }
    if (!best) { el.textContent = '-'; return; }
    if (nowMs >= best.startMs && nowMs < best.endMs) {
      var leftMin = Math.max(1, Math.ceil((best.endMs - nowMs) / 60000));
      el.textContent = 'WoE is LIVE (' + leftMin + 'm left)';
      return;
    }
    var totalMin = Math.floor((best.startMs - nowMs) / 60000);
    var days = Math.floor(totalMin / 1440);
    var hours = Math.floor((totalMin % 1440) / 60);
    var mins = totalMin % 60;
    el.textContent = 'Next WoE in ' + days + 'd ' + hours + 'h ' + mins + 'm';
  }
  renderCountdown();
  setInterval(renderCountdown, 60000);
})();
var warDaysEl = document.getElementById('war-days');
if (warDaysEl) warDaysEl.textContent = DATA.history_days;

document.getElementById('chip-vendor').innerHTML = '<strong>' + DATA.summary.vendor_listings.toLocaleString() + '</strong> vendor listings';
document.getElementById('chip-buyer').innerHTML = '<strong>' + DATA.summary.buyer_orders.toLocaleString() + '</strong> buyer orders';
document.getElementById('chip-priced').innerHTML = '<strong>' + DATA.summary.priced_items.toLocaleString() + '</strong> items priced';
document.getElementById('chip-level').innerHTML = 'Char level <strong>' + DATA.char_level + '</strong>';
</script>
</body>
</html>
"""


def _read_seed_rows(path: Path) -> list[dict]:
    """CSV seed reader shared by war_supplies.csv / woe_schedule.csv: skips
    comment lines (leading '#') before handing the rest to csv.DictReader."""
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(line for line in f if not line.lstrip().startswith("#"))
        return list(reader)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # em dash / arrow glyphs on Windows consoles
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = load_settings()
    store = Store(s.database_url)
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    listings = store.latest_listings()
    buy_orders = store.latest_buy_orders()
    from .overrides import apply_drop_overrides
    drops = apply_drop_overrides(store.all_drops())

    # War Chest seeds: repo-root seeds/ (same dir as farm_spots.csv, loaded by
    # scripts/load_seeds.py) -- report.py lives 3 levels below the repo root.
    seeds_dir = Path(__file__).resolve().parent.parent.parent / "seeds"
    war_items = [
        {"item_id": int(r["item_id"]), "name": r["name"]}
        for r in _read_seed_rows(seeds_dir / "war_supplies.csv")
    ]
    woe = [
        {
            "weekday": int(r["weekday"]),
            "start_hh": int(r["start_hh"]),
            "start_mm": int(r["start_mm"]),
            "duration_min": int(r["duration_min"]),
        }
        for r in _read_seed_rows(seeds_dir / "woe_schedule.csv")
    ]

    # Item icons: one-time download into a disk cache (first build takes a few
    # minutes for ~2.4k icons), then embedded as data URIs to stay offline.
    item_ids = ({l.item_id for l in listings} | {b.item_id for b in buy_orders}
                | {d["item_id"] for d in drops})
    icon_cache = Path(__file__).resolve().parent.parent / ".icon-cache"
    ensure_icons(item_ids, icon_cache)
    icons = icon_data_uris(item_ids, icon_cache)

    # Monster sprites: cache for every known mob; build_html embeds only the
    # ones referenced by grind/lottery rows.
    mob_ids = store.monster_ids()
    mob_cache = icon_cache / "mobs"
    ensure_mob_icons(mob_ids, mob_cache)
    mob_icons = mob_icon_data_uris(mob_ids, mob_cache)

    html = build_html(
        listings,
        buy_orders,
        store.sales_since(SALES_WINDOW_DAYS),
        drops,
        store.farm_spots(),
        store.turnins(),
        s.char_level,
        generated_at,
        store.monster_meta_all(),
        store.best_spawns(),
        icons,
        store.item_info_all(),
        mob_icons,
        store.price_history(),
        store.npc_sell_map(),
        store.latest_snapshot_ts(),
        merchant_history=store.listings_history(),
        pnl=strategy_pnl(store.trades_all()),
        balances=store.balances_all(),
        war_items=war_items,
        woe=woe,
    )
    out_path = Path(__file__).resolve().parent.parent / "market_report.html"
    out_path.write_text(html, encoding="utf-8")
    print(str(out_path))
    try:
        os.startfile(str(out_path))  # noqa: S606 - best-effort local convenience open
    except Exception:
        pass


if __name__ == "__main__":
    main()
