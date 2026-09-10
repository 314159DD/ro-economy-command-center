import json
import pathlib

from ro_collector.parse_ragnapi import parse_ragnapi_monster

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_parse_sleeper_meta_and_spawns():
    data = json.loads((FIXTURES / "ragnapi_1386.json").read_text(encoding="utf-8"))
    meta, spawns = parse_ragnapi_monster(data)

    assert meta.monster_id == 1386
    assert meta.name == "sleeper"
    assert (meta.size, meta.race, meta.element) == ("medium", "formless", "earth")
    assert meta.level == 67
    assert meta.hp == 8237          # parsed from "8,237"
    assert meta.flee == 217
    assert meta.def_ == 49          # first int of "49 + 100 ~ 124"
    assert meta.base_exp == 3603    # from "3,603"
    assert meta.job_exp == 2144
    assert meta.aspd == 132.5
    assert meta.boss_class == "normal"  # Sleeper is an ordinary mob

    # densest spawn is juno_field (70), which maps to the seed's yuno_fild06
    densest = max(spawns, key=lambda s: s.amount)
    assert densest.map_name == "juno_field"
    assert densest.amount == 70
    assert all(s.monster_id == 1386 for s in spawns)


def test_best_element_is_highest_damage_taken():
    data = json.loads((FIXTURES / "ragnapi_1386.json").read_text(encoding="utf-8"))
    meta, _ = parse_ragnapi_monster(data)
    elem = data["elementalDamage"]
    assert meta.best_element == max(elem, key=elem.get)


def test_missing_fields_do_not_crash():
    meta, spawns = parse_ragnapi_monster({"monster_id": 9999})
    assert meta.monster_id == 9999
    assert meta.hp is None
    assert meta.best_element == ""
    assert spawns == []
