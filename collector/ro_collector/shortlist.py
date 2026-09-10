"""Render the grind/market/exp shortlist as markdown. The day-one payoff."""
from collections import defaultdict

from .config import load_settings
from .db import Store
from .overrides import apply_drop_overrides
from .scoring import demand_map, exp_per_zeny, market_stats, spot_ev, value_map

SALES_WINDOW_DAYS = 7


def build_report(listings, buy_orders, sales, drops, spots, turnins, char_level: int,
                 meta_by_id=None, best_spawn_by_id=None) -> str:
    markets = market_stats(listings, sales, SALES_WINDOW_DAYS)
    demand = demand_map(buy_orders)  # item_id -> guaranteed buyer price
    values = value_map(markets, demand)
    demand_ids = set(demand)
    drops_by_monster: dict[int, list] = defaultdict(list)
    for d in drops:
        drops_by_monster[d["monster_id"]].append(d)

    evs = [spot_ev(s, drops_by_monster, values, demand_ids, meta_by_id, best_spawn_by_id)
           for s in spots]
    open_spots = sorted((e for e in evs if e.min_level <= char_level), key=lambda e: -e.zeny_per_hour)
    locked = sorted((e for e in evs if e.min_level > char_level), key=lambda e: -e.zeny_per_hour)

    lines = [
        f"# Shortlist (char level {char_level})", "",
        "> ✓ = a live buyer order backs this drop (provably sells now). Untagged",
        "> values are vendor asking-prices, heavily discounted until proven.", "",
        "## GRIND BOARD", "",
    ]
    for i, e in enumerate(open_spots, 1):
        tag = "calibrated" if e.calibrated else "estimated"
        tops = ", ".join(f"{n} ({z:,}/hr){' ✓' if backed else ''}" for n, z, backed in e.top_drops)
        map_txt = f"{e.best_map} x{e.density}" if e.best_map else e.map
        lines.append(f"{i}. **{e.spot_name}** ({map_txt}) - **{e.zeny_per_hour:,} z/hr** [{tag}]")
        extras = []
        if e.exp_per_hour:
            extras.append(f"~{e.exp_per_hour:,} base exp/hr")
        if e.arrow:
            extras.append(f"best arrow: {e.arrow}")
        if extras:
            lines.append(f"   {' | '.join(extras)}")
        if tops:
            lines.append(f"   top drops: {tops}")
        for note in e.card_notes:
            lines.append(f"   card: {note}")
        if e.notes:
            lines.append(f"   note: {e.notes}")
    lines += ["", "## LOCKED SPOTS", ""]
    for e in locked:
        notes_txt = f" - {e.notes}" if e.notes else ""
        lines.append(
            f"- {e.spot_name} ({e.map}) - {e.zeny_per_hour:,} z/hr - unlocks at level {e.min_level}{notes_txt}"
        )

    lines += ["", "## BUYER ORDERS", ""]
    demand: dict[int, dict] = {}
    for b in buy_orders:
        d = demand.setdefault(b.item_id, {"name": b.item_name, "qty": 0, "price": b.price, "total": 0})
        d["qty"] += b.amount
        d["price"] = max(d["price"], b.price)
        d["total"] += b.amount * b.price
    best_source = {}
    for dr in drops:
        cur = best_source.get(dr["item_id"])
        if cur is None or dr["rate"] > cur[1]:
            best_source[dr["item_id"]] = (dr["monster_name"], dr["rate"])
    for item_id, d in sorted(demand.items(), key=lambda kv: -kv[1]["total"]):
        src = best_source.get(item_id)
        src_txt = f" - farm: {src[0]} ({src[1]}%)" if src else ""
        lines.append(f"- {d['name']}: {d['qty']:,} wanted @ up to {d['price']:,} z (total {d['total']:,} z){src_txt}")

    lines += ["", "## EXP PLANNER", ""]
    for r in exp_per_zeny(turnins, markets, char_level):
        if r["turnin_cost"] is not None:
            lines.append(
                f"- {r['target_name']} x{r['qty']} @ {r['npc']} ({r['location']}): "
                f"{r['turnin_cost']:,} z per turn-in -> {r['base_exp_per_1k_zeny']:,} base exp / 1k z"
            )
        else:
            lines.append(f"- {r['target_name']} x{r['qty']} @ {r['npc']}: {r.get('note', '')}")
    return "\n".join(lines)


def main() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # em dash / arrow glyphs on Windows consoles
    s = load_settings()
    store = Store(s.database_url)
    print(
        build_report(
            store.latest_listings(),
            store.latest_buy_orders(),
            store.sales_since(SALES_WINDOW_DAYS),
            apply_drop_overrides(store.all_drops()),
            store.farm_spots(),
            store.turnins(),
            s.char_level,
            store.monster_meta_all(),
            store.best_spawns(),
        )
    )


if __name__ == "__main__":
    main()
