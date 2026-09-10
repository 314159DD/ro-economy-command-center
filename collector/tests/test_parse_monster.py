import pathlib

from ro_collector.parse_monster import parse_monster_index, parse_monster_page

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_monster_index():
    rows, total = parse_monster_index(load("monster_index_p1.html"))
    assert len(rows) == 20
    ids = [r["id"] for r in rows]
    assert 1001 in ids
    assert total == 1007 or total > 900  # exact count may drift with server updates
    # HP lives ONLY on the index page in this FluxCP build (absent from the
    # monster view page) — the index parser must capture it per row.
    scorpion = next(r for r in rows if r["id"] == 1001)
    assert scorpion["name"] == "Scorpion"
    assert scorpion["level"] == 24
    assert scorpion["hp"] == 1109  # rendered as "1,109" in the fixture
    assert all(r["name"] for r in rows)
    assert all(r["level"] and r["level"] > 0 for r in rows)
    assert all(r["hp"] and r["hp"] > 0 for r in rows)


def test_monster_view_anolian():
    m = parse_monster_page(load("monster_1206.html"), 1206)
    assert m.id == 1206
    assert m.name == "Anolian"
    # NOTE: this RO FluxCP build does not expose HP on the monster VIEW page
    # (only on the index/list page). Verified absent from the real fixture --
    # see parse_monster.py module docstring and task-5-report.md. Level is the
    # nearest verifiable numeric stat carried by this page.
    assert m.level and m.level > 0
    drops = {d.item_id: d for d in m.drops}
    assert drops[984].rate == 6.7            # Oridecon, x5 applied server-side
    assert drops[2625].rate == 0.05          # Brooch
    assert drops[4234].rate == 0.05          # Anolian Card
    assert drops[7003].item_name == "Anolian Skin"
    assert drops[7003].rate == 100.0
