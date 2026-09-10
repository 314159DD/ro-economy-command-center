"""Drop-rate corrections the CP monster DB does not reflect.

The server nerfs some drops server-side without updating the CP's monster module
(first known case: Sleeper's Great Nature, listed at 100% but nerfed by 75%
per the the server documentation site). Corrections live in seeds/drop_overrides.csv
(monster_id, item_id, multiplier, note) and are applied wherever scoring
consumes drops. Add a row whenever the docs or in-game reality contradict
the CP; source every row in its note column.
"""
import csv
import logging
import pathlib

log = logging.getLogger("ro.overrides")

SEEDS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "seeds"


def load_drop_overrides(seeds_dir=None) -> dict:
    """(monster_id, item_id) -> rate multiplier."""
    path = pathlib.Path(seeds_dir or SEEDS_DIR) / "drop_overrides.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        rows = [line for line in f if not line.lstrip().startswith("#")]
    out: dict = {}
    for r in csv.DictReader(rows):
        out[(int(r["monster_id"]), int(r["item_id"]))] = float(r["multiplier"])
    return out


def apply_drop_overrides(drops: list[dict], overrides: dict | None = None) -> list[dict]:
    """Return drops with corrected rates (originals are not mutated)."""
    ov = load_drop_overrides() if overrides is None else overrides
    if not ov:
        return drops
    out = []
    hit = 0
    for d in drops:
        key = (d["monster_id"], d["item_id"])
        if key in ov:
            d = dict(d)
            d["rate"] = round(float(d["rate"]) * ov[key], 4)
            hit += 1
        out.append(d)
    if hit:
        log.info("applied %d drop-rate overrides", hit)
    return out
