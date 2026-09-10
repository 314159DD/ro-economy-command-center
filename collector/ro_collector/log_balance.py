"""Log a character's current zeny balance and see progress toward 1B zeny.

Examples (from collector/):
  .venv\\Scripts\\python -m ro_collector.log_balance 12000000
  .venv\\Scripts\\python -m ro_collector.log_balance 12_000_000
"""
import argparse
import sys

from .config import load_settings
from .db import Store

GOAL = 1_000_000_000


def _parse_zeny(s: str) -> int:
    return int(s.replace("_", ""))


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Log a zeny balance snapshot.")
    ap.add_argument("zeny", type=_parse_zeny, help="current total zeny, e.g. 12_000_000")
    args = ap.parse_args(argv)

    store = Store(load_settings().database_url)
    store.insert_balance(args.zeny)
    pct = args.zeny / GOAL * 100
    print(f"Balance logged: {args.zeny:,} z ({pct:.1f}% of 1B goal)")


if __name__ == "__main__":
    main()
