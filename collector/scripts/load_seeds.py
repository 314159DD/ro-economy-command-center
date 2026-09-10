"""Load seeds/farm_spots.csv into the farm_spots table.
Usage (from collector/): .venv\\Scripts\\python scripts/load_seeds.py"""
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[0].parent))
from ro_collector.config import load_settings  # noqa: E402
from ro_collector.db import Store  # noqa: E402

csv_path = pathlib.Path(__file__).resolve().parents[2] / "seeds" / "farm_spots.csv"
rows = []
with csv_path.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rows.append({
            "name": r["name"],
            "map": r["map"],
            "monster_ids": [int(x) for x in r["monster_ids"].split(";")],
            "min_level": int(r["min_level"]),
            "kills_per_hour": int(r["kills_per_hour"]),
            "arrows_per_hour": int(r["arrows_per_hour"]),
            "arrow_price": int(r["arrow_price"]),
            "notes": r["notes"],
        })
Store(load_settings().database_url).upsert_farm_spots(rows)
print(f"loaded {len(rows)} farm spots")
