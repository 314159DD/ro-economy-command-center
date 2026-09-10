"""Parse FluxCP monster module pages: paginated index and per-monster view.

The INDEX page's data table is `<table class="horizontal-table">` (same
anchor as the merchant pages, unique on the page). Each monster row is:
id-link | icon (empty text) | name | level | hp | size | race | element |
base exp | job exp. HP and exp values are comma-formatted ("1,109"). The
index is the ONLY place this FluxCP build exposes HP (see below), so
`parse_monster_index` captures name/level/hp per row -- the refresh
orchestrator merges these with per-monster drop data by id.

The real per-monster VIEW page (`monster_1206.html`, an actual RO capture)
has three `<table class="vertical-table">` elements: an info table (id,
name, level, stats), a drop table, and a monster-skills table -- plus a
`<table class="character-stats">` nested *inside* the info table for
STR/AGI/VIT/INT/DEX/LUK. The parser anchors on `vertical-table` explicitly
rather than scanning every `<table>` on the page, so it never mistakes the
nested stats table or the skills table for the info/drop tables.

Two real-markup surprises vs. a naive read of the page:

1. The info table on this build genuinely has **no HP field** -- confirmed
   by a case-insensitive substring search across the whole fixture (zero
   hits for "hp") and a structural dump of every row of the info table.
   FluxCP shows HP only on the monster index/list page (sortable `HP`
   column), not on the per-monster view. Since the scraper's per-monster
   fetch only sees the view page, `Monster.hp` is `None` here -- this is a
   property of the real page, not a parser gap. If HP is needed later, it
   will have to come from a separate index-page crawl merged in by id.

2. Each drop row has 4 `<td>`s, not 3: item-id-link | item-icon (empty
   text) | item-name | rate. The icon cell's `get_text()` is `""`, so drops
   are parsed by filtering to non-empty cell texts (`[id, name, rate]`)
   rather than assuming a fixed 3-column layout. The item id is read from
   the row's `module=item&action=view&id=<n>` link href (robust even if the
   cell text formatting shifts), falling back to the first non-empty cell
   if no link is found.
"""
import re

from bs4 import BeautifulSoup

from .models import Drop, Monster

_RECORDS_RE = re.compile(r"total of\s*([\d,]+)\s*record", re.I)
_VIEW_ID_RE = re.compile(r"module=monster&(?:amp;)?action=view&(?:amp;)?id=(\d+)")
_ITEM_ID_RE = re.compile(r"module=item&(?:amp;)?action=view&(?:amp;)?id=(\d+)")
_PCT_RE = re.compile(r"([\d.]+)\s*%")


def _int_or_none(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_monster_index(html: str) -> tuple[list[dict], int]:
    """Return ([{id, name, level, hp}, ...], total_records) from an index page.

    Rows are anchored on the `horizontal-table` data table and each row's
    monster-view link; the icon cell has empty text, so after filtering to
    non-empty cell texts the row reads [id, name, level, hp, size, race,
    element, base_exp, job_exp].
    """
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: set[int] = set()
    table = soup.find("table", class_="horizontal-table")
    for tr in (table.find_all("tr") if table else []):
        link = tr.find("a", href=True, class_="link-to-monster") or tr.find("a", href=True)
        m = _VIEW_ID_RE.search(link["href"]) if link else None
        if not m:
            continue
        mid = int(m.group(1))
        if mid in seen:
            continue
        seen.add(mid)
        non_empty = [t for t in (td.get_text(" ", strip=True) for td in tr.find_all("td")) if t]
        # non_empty = [id, name, level, hp, size, race, element, base_exp, job_exp]
        name = non_empty[1] if len(non_empty) > 1 else ""
        level = _int_or_none(non_empty[2]) if len(non_empty) > 2 else None
        hp = _int_or_none(non_empty[3]) if len(non_empty) > 3 else None
        rows.append({"id": mid, "name": name, "level": level, "hp": hp})
    rm = _RECORDS_RE.search(soup.get_text())
    total = int(rm.group(1).replace(",", "")) if rm else 0
    return rows, total


def _info_table(soup):
    """The monster info table is the first `vertical-table` on the view page."""
    return soup.find("table", class_="vertical-table")


def _label_cell(table, label: str):
    """Find a cell in `table` whose text is exactly `label`; return its sibling cell."""
    if table is None:
        return None
    for cell in table.find_all(["td", "th"]):
        if cell.get_text(strip=True) == label:
            return cell.find_next_sibling(["td", "th"])
    return None


def _label_text(table, label: str) -> str:
    sib = _label_cell(table, label)
    return sib.get_text(strip=True) if sib else ""


def _label_int(table, label: str) -> int | None:
    sib = _label_cell(table, label)
    if sib is None:
        return None
    digits = re.sub(r"[^\d]", "", sib.get_text())
    return int(digits) if digits else None


def _parse_drops(soup) -> list[Drop]:
    drops: list[Drop] = []
    for table in soup.find_all("table", class_="vertical-table"):
        header_row = table.find("tr")
        if header_row is None:
            continue
        header_text = " ".join(c.get_text(strip=True) for c in header_row.find_all(["th", "td"]))
        if "Item ID" not in header_text:
            continue
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if not tds:
                continue
            texts = [td.get_text(" ", strip=True) for td in tds]
            non_empty = [t for t in texts if t]
            if len(non_empty) < 3:
                continue
            link = tr.find("a", href=True)
            id_match = _ITEM_ID_RE.search(link["href"]) if link else None
            if id_match:
                item_id = int(id_match.group(1))
            elif non_empty[0].isdigit():
                item_id = int(non_empty[0])
            else:
                continue
            item_name = non_empty[1]
            pm = _PCT_RE.search(non_empty[-1])
            if not pm:
                continue
            drops.append(Drop(item_id=item_id, item_name=item_name, rate=float(pm.group(1))))
        break  # only one drop table per monster page
    return drops


def parse_monster_page(html: str, monster_id: int) -> Monster:
    soup = BeautifulSoup(html, "lxml")
    info = _info_table(soup)

    name = _label_text(info, "Name")
    if not name:
        h3 = soup.find("h3")
        if h3:
            hm = re.search(r"#\d+:\s*(.+)", h3.get_text(" ", strip=True))
            if hm:
                name = hm.group(1).strip()

    return Monster(
        id=monster_id,
        name=name,
        level=_label_int(info, "Level"),
        hp=_label_int(info, "HP") or _label_int(info, "Max HP"),
        drops=_parse_drops(soup),
    )
