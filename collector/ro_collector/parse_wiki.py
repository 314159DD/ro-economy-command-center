"""Parse the server wiki: Repeatable_Quests/ into TurnInQuest rows.

Both quest tables render as plain 9-column mkdocs tables (no colspan in
practice):
  item table: NPC, Location, Min Level, Max Level, Items, Base EXP, Job EXP,
              Base EXP Per Item, Job EXP Per Item
  hunt table: NPC, Location, Min Level, Max Level, Monster, Base EXP, Job EXP,
              Base EXP Per Monster, Job EXP Per Monster

The item table's "Items" column is a single combined cell like
"25 Fluff" or "50 Antelope Horn" -- qty and item name are NOT separate
columns, unlike the brief's initial assumption. Both tables are still parsed
from the end (cells[-4]/[-3] = totals Base/Job EXP, cells[-5] = name column)
so a future colspan on either header can't silently break indexing.

Hunt rewards are per-50 kills (100/150 hunts scale linearly) -> qty=50.
Hunt monster names may carry a trailing '*' (quest-gated maps) -- stripped.
"""
import re

from bs4 import BeautifulSoup

from .models import TurnInQuest

# From the wiki's "Item Purchase Locations" section. Antelope Horn: Discount
# skill does not apply and the item cannot be player-vended.
NPC_PURCHASABLE = {
    "Bill of Birds": "Morroc Ruins (moc_ruins 81/113 or 93/53)",
    "Acorn": "Moscovia, Acorn Dealer (moscovia 208/182)",
    "Antelope Horn": "Niflheim, Tool Dealer (niflheim 218/197), no Discount",
}

_INT = re.compile(r"^[\d,]+$")
_QTY_ITEM = re.compile(r"^(\d+)\s+(.+)$")


def _num(text: str) -> int:
    return int(text.replace(",", ""))


_PRICE = re.compile(r"[\d,]+")


def parse_modified_sales(html: str) -> list[dict]:
    """the server wiki: Modified_Sales_Prices — the server's custom NPC shop prices.
    Rows: item name | original (mainline) sell | modified (server-true) sell.
    Cells look like "120,000 Z"."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        first = table.find("tr")
        if first is None:
            continue
        header = " ".join(c.get_text(" ", strip=True).lower() for c in first.find_all(["th", "td"]))
        if "modified price" not in header:
            continue
        for tr in table.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 3:
                continue
            orig, mod = _PRICE.search(cells[1]), _PRICE.search(cells[2])
            if orig and mod:
                rows.append({"name": cells[0], "original": _num(orig.group()), "modified": _num(mod.group())})
    return rows


def _parse_table(table, form: str) -> list[TurnInQuest]:
    quests = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 8 or not _INT.match(cells[2].strip()):
            continue  # header or malformed row
        npc, location = cells[0], cells[1]
        min_lv, max_lv = _num(cells[2]), _num(cells[3])
        base, job = _num(cells[-4]), _num(cells[-3])
        name_cell = cells[-5]
        if form == "item":
            m = _QTY_ITEM.match(name_cell)
            if not m:
                continue
            qty, target = int(m.group(1)), m.group(2).strip()
        else:
            target = name_cell.rstrip("*").strip()  # * marks quest-gated maps
            qty = 50
        quests.append(
            TurnInQuest(
                form=form, npc=npc, location=location, min_level=min_lv,
                max_level=max_lv, target_name=target, qty=qty,
                base_exp=base, job_exp=job,
            )
        )
    return quests


def parse_repeatable_quests(html: str) -> list[TurnInQuest]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    quests: list[TurnInQuest] = []
    for table in tables:
        headers = " ".join(th.get_text(strip=True) for th in table.find_all("th"))
        if "Base EXP Per Item" in headers:
            quests += _parse_table(table, "item")
        elif "Base EXP Per Monster" in headers:
            quests += _parse_table(table, "hunt")
    return quests
