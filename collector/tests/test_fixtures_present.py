import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

CASES = [
    ("vendors_p1.html", ["Merchant", "record"]),
    ("buyers_p1.html", ["Asking Price"]),
    ("monster_index_p1.html", ["module=monster"]),
    ("monster_1206.html", ["Anolian", "Drop"]),
    ("wiki_repeatable_quests.html", ["Repeatable", "Antelope Horn"]),
]


@pytest.mark.parametrize("name,markers", CASES)
def test_fixture_present_with_markers(name, markers):
    path = FIXTURES / name
    assert path.exists(), f"fixture {name} missing — run scripts/capture_fixtures.py"
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        assert marker in text, f"{name} lacks expected marker {marker!r}"


def test_fixtures_contain_no_session_cookie():
    for p in FIXTURES.glob("*.html"):
        assert "PHPSESSID" not in p.read_text(encoding="utf-8")
