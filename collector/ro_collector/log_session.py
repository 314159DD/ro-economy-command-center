"""Log a real farm session to calibrate a spot's kills/hr.

Two ways to give kills:
  --kills 900                      you eyeballed ~900 kills
  --loot "Great Nature:410"        back-calculate from a drop count using the
                                   server-true drop rate (kills = count / rate)

Either updates farm_spots.kills_per_hour + flips the spot to [calibrated], and
records the session in farm_sessions.

Examples (from collector/):
  .venv\\Scripts\\python -m ro_collector.log_session --spot Sleepers --minutes 60 --kills 1150
  .venv\\Scripts\\python -m ro_collector.log_session --spot Sleepers --minutes 60 --loot "Great Nature:410"
"""
import argparse
import sys

from .config import load_settings
from .db import Store
from .overrides import apply_drop_overrides
from .scoring import kills_from_loot


def _parse_loot(text: str) -> dict:
    loot = {}
    for part in text.split(","):
        if ":" in part:
            name, count = part.rsplit(":", 1)
            loot[name.strip()] = int(count.strip())
    return loot


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Calibrate a farm spot from a real session.")
    ap.add_argument("--spot", required=True, help="farm_spots.name (exact)")
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--kills", type=int, help="observed kill count")
    ap.add_argument("--loot", help='e.g. "Great Nature:410,Fine Sand:120" (back-calc from a drop)')
    args = ap.parse_args(argv)

    store = Store(load_settings().database_url)
    spot = store.farm_spot_by_name(args.spot)
    if spot is None:
        names = [s["name"] for s in store.farm_spots()]
        print(f"No spot named {args.spot!r}. Known spots: {', '.join(names)}")
        sys.exit(1)

    loot = _parse_loot(args.loot) if args.loot else {}
    kills = args.kills
    if kills is None:
        if not loot:
            print("Provide --kills or --loot to compute kills/hr.")
            sys.exit(1)
        # back-calculate kills from the highest-rate matching drop
        drops = [d for d in apply_drop_overrides(store.all_drops()) if d["monster_id"] in spot["monster_ids"]]
        kills = kills_from_loot(loot, drops)
        if kills is None:
            print("Could not match any --loot item to this spot's drop table.")
            sys.exit(1)

    kph = round(kills / (args.minutes / 60))
    store.calibrate_spot(args.spot, kph)
    store.insert_farm_session(spot["id"], args.minutes, loot or {"kills": kills})
    print(f"Calibrated {args.spot}: {kills} kills in {args.minutes} min -> {kph:,} kills/hr [calibrated]")


if __name__ == "__main__":
    main()
