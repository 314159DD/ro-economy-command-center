"""Parse the CP item view page (real RO capture: item_view_1734.html).

The info table lays out TWO th/td pairs per row ("Name | Orc Archer Bow |
Weight | 160"), so the parser must walk label/value pairs, not take the
first pair per row. Sell is the server-true NPC price — the one field that
burned us when mainline Hercules values were wrong (Khukri: 120k mainline
vs 25k on this server)."""
import pathlib

from ro_collector.parse_item import parse_item_page

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "item_view_1734.html"


def test_parses_real_item_view_page():
    info = parse_item_page(FIXTURE.read_text(encoding="utf-8"), 1734)
    assert info["name"] == "Orc Archer Bow"
    assert info["item_type"] == "Weapon - Bow"
    assert info["weight"] == 160
    assert info["atk"] == 120
    assert info["defense"] == 0
    assert info["slots"] == 0
    assert info["equip_level"] == 65
    assert info["npc_sell"] == 10          # server-true NPC sell price


def test_login_redirect_returns_none():
    html = "<html><body>Login required <a href='?module=account&action=login'>Login</a></body></html>"
    assert parse_item_page(html, 1734) is None
