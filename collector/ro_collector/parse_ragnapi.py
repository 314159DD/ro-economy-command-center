"""Parse a RagnaAPI monster JSON into flat meta + spawn rows.

RagnaAPI (ragnapi.com) fills gaps the server CP lacks: spawn maps + density,
combat stats (flee/def/element) for kill-speed and arrow choice, and per-kill
base/job EXP. Drop RATES are NOT taken from here -- the CP is authoritative for
this server's multiplier-applied rates. Numbers arrive as comma strings and def
arrives as "base + refine ~ max"; this module normalises them.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MonsterMeta:
    monster_id: int
    name: str
    size: str
    race: str
    element: str
    element_power: int
    level: int | None
    hp: int | None
    flee: int | None
    hit: int | None
    def_: int | None
    mdef: int | None
    aspd: float | None
    base_exp: int | None
    job_exp: int | None
    best_element: str  # element the mob takes the most damage from (best arrow)
    boss_class: str    # 'normal' | 'miniboss' | 'mvp' (from skills.mode)


@dataclass(frozen=True)
class MonsterSpawn:
    monster_id: int
    map_name: str
    map_number: int
    amount: int
    map_type: str


def _int(text) -> int | None:
    if text is None:
        return None
    digits = re.sub(r"[^\d]", "", str(text).split("~")[0].split("+")[0])
    return int(digits) if digits else None


def _lead_int(text) -> int | None:
    """First integer in a compound stat like '49 + 100 ~ 124' -> 49 (base value)."""
    if text is None:
        return None
    m = re.search(r"\d+", str(text))
    return int(m.group(0)) if m else None


def _float(text) -> float | None:
    if text is None:
        return None
    m = re.search(r"[\d.]+", str(text))
    return float(m.group(0)) if m else None


def parse_ragnapi_monster(data: dict) -> tuple[MonsterMeta, list[MonsterSpawn]]:
    ms = data.get("main_stats", {})
    elem = data.get("elementalDamage", {}) or {}
    best_element = max(elem, key=elem.get) if elem else ""
    mid = int(data["monster_id"])

    # RO's skill 'mode' flags mark bosses: MVPs carry both 'boss' and 'mvp';
    # mini-bosses (mimics, tower guardians) carry 'boss' without 'mvp'.
    mode = (data.get("skills", {}) or {}).get("mode", []) or []
    boss_class = "mvp" if "mvp" in mode else ("miniboss" if "boss" in mode else "normal")

    meta = MonsterMeta(
        monster_id=mid,
        name=data.get("monster_info", ""),
        size=data.get("size", ""),
        race=data.get("race", ""),
        element=data.get("type", ""),
        element_power=int(data.get("element_power") or 0),
        level=_int(ms.get("level")),
        hp=_int(ms.get("hp")),
        flee=_int(ms.get("flee")),
        hit=_int(ms.get("hit")),
        def_=_lead_int(ms.get("def")),
        mdef=_lead_int(ms.get("m_def")),
        aspd=_float(ms.get("aspd")),
        base_exp=_int(ms.get("base_exp")),
        job_exp=_int(ms.get("job_exp")),
        best_element=best_element,
        boss_class=boss_class,
    )

    spawns = []
    for m in data.get("maps", []) or []:
        amount = _int(m.get("amount"))
        if not m.get("name") or not amount:
            continue
        spawns.append(MonsterSpawn(
            monster_id=mid,
            map_name=m.get("name", ""),
            map_number=int(m.get("number") or 0),
            amount=amount,
            map_type=m.get("type", ""),
        ))
    return meta, spawns
