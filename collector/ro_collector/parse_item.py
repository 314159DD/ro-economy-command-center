"""Parse a FluxCP item view page (module=item&action=view&id=N) into a dict.

The item info lives in `<table class="vertical-table">` rows that hold TWO
th/td pairs per row ("Name | Orc Archer Bow | Weight | 160"), so the parser
walks each row's cells as label/value pairs. Labels are lowercased so column
order or extra rows don't break it; anything missing is None.

`npc_sell` ("Sell") is the server-true NPC price — authoritative over any
mainline Hercules value (server customizes shop prices; a Khukri sells for
25k here vs 120k mainline, a lesson that cost the player 50k).
"""
import re

from bs4 import BeautifulSoup


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"-?[\d,]+", text)
    return int(m.group().replace(",", "")) if m else None


def parse_item_page(html: str, item_id: int) -> dict | None:
    """None when the page isn't an item view (login redirect, unknown id)."""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    for table in soup.select("table.vertical-table"):
        for tr in table.select("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            label = None
            for cell in cells:
                if cell.name == "th":
                    label = cell.get_text(" ", strip=True).lower().rstrip(":")
                elif label is not None:
                    fields.setdefault(label, cell.get_text(" ", strip=True))
                    label = None
    name = fields.get("identified name") or fields.get("name")
    if not name:
        return None
    return {
        "item_id": item_id,
        "name": name,
        "item_type": fields.get("type") or None,
        "weight": _to_int(fields.get("weight")),
        "atk": _to_int(fields.get("attack") or fields.get("atk")),
        "defense": _to_int(fields.get("defense") or fields.get("def")),
        "slots": _to_int(fields.get("slots")),
        "equip_level": _to_int(fields.get("min equip level") or fields.get("equip level")
                               or fields.get("required level")),
        "npc_sell": _to_int(fields.get("sell")),
    }
