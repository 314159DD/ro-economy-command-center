import pathlib

from ro_collector.parse_wiki import NPC_PURCHASABLE, parse_repeatable_quests

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_parse_both_quest_tables():
    quests = parse_repeatable_quests((FIXTURES / "wiki_repeatable_quests.html").read_text(encoding="utf-8"))
    items = [q for q in quests if q.form == "item"]
    hunts = [q for q in quests if q.form == "hunt"]
    assert len(items) >= 15
    assert len(hunts) >= 20

    fluff = next(q for q in items if q.target_name == "Fluff")
    assert (fluff.npc, fluff.min_level, fluff.max_level) == ("Langry", 2, 20)
    assert (fluff.qty, fluff.base_exp, fluff.job_exp) == (25, 770, 60)

    horn = next(q for q in items if q.target_name == "Antelope Horn")
    assert (horn.min_level, horn.max_level, horn.qty) == (70, 85, 50)
    assert horn.base_exp == 516_978

    sala = next(q for q in hunts if q.target_name == "Salamander")
    assert (sala.min_level, sala.max_level, sala.qty) == (75, 98, 50)
    assert sala.base_exp == 8_600_000


def test_npc_purchasable_items_flagged():
    assert "Antelope Horn" in NPC_PURCHASABLE
    assert "Acorn" in NPC_PURCHASABLE
    assert "Bill of Birds" in NPC_PURCHASABLE
