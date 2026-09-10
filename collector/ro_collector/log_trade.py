"""Log a real trade to the ledger and see per-strategy realized P&L.

<item> may be a numeric item_id or a name (matched case-insensitively). If the
name matches more than one item, the first match is used and printed so you
can confirm it was the right one. If it matches nothing, the trade is still
logged with item_id=None and the raw string as the item name.

Examples (from collector/):
  .venv\\Scripts\\python -m ro_collector.log_trade --buy "Poring Card" --qty 3 --price 50000 --strategy flip
  .venv\\Scripts\\python -m ro_collector.log_trade --sell 909 --qty 15 --price 150 --strategy mm --note "relisted from prt_mk"
"""
import argparse
import sys

from .config import load_settings
from .db import Store
from .scoring import strategy_pnl

STRATEGIES = ("flip", "snipe", "corner", "mm", "grind", "other")


def _resolve_item(store: Store, item: str) -> tuple[int | None, str]:
    if item.isdigit():
        item_id = int(item)
        name = store.item_name_by_id(item_id)
        return item_id, name or f"Item #{item_id}"
    matches = store.items_by_name(item)
    if not matches:
        return None, item
    if len(matches) > 1:
        print(f"Multiple items match {item!r}; using {matches[0]['name']!r} (id {matches[0]['id']}).")
    return matches[0]["id"], matches[0]["name"]


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Log a real trade to the ledger.")
    side_group = ap.add_mutually_exclusive_group(required=True)
    side_group.add_argument("--buy", action="store_true", help="this trade was a buy")
    side_group.add_argument("--sell", action="store_true", help="this trade was a sell")
    ap.add_argument("item", help="item_id (numeric) or item name")
    ap.add_argument("--qty", type=int, required=True)
    ap.add_argument("--price", type=int, required=True, help="zeny per unit")
    ap.add_argument("--strategy", choices=STRATEGIES, default="other")
    ap.add_argument("--note")
    args = ap.parse_args(argv)

    store = Store(load_settings().database_url)
    item_id, item_name = _resolve_item(store, args.item)
    side = "buy" if args.buy else "sell"

    store.insert_trade(item_id, item_name, side, args.qty, args.price, args.strategy, args.note)
    print(f"Logged {side} {args.qty:,} x {item_name} @ {args.price:,} z [{args.strategy}]")

    pnl = strategy_pnl(store.trades_all())
    for strategy, s in sorted(pnl.items(), key=lambda kv: -kv[1]["realized"]):
        print(f"  {strategy}: realized {s['realized']:,} z, open {s['open_qty']} qty / {s['open_cost']:,} z cost")


if __name__ == "__main__":
    main()
