"""Parse FluxCP merchant pages (vendors and buyers) into Listing rows.

Observed row layout (vendors): merchant | shop | position | item-icon | item
name | amount | price | cards  (the 'Item' header spans icon+name). Buyers
lack the cards column. The parser anchors on the row's item link (href
contains id=<n>) and locates the enclosing <td> to slice the remaining
cells positionally, rather than assuming a fixed cell count.

Position (map/x/y) is read directly off the "Copy Navi to Clipboard" button's
data-map/data-x/data-y attributes -- more reliable than regexing the cell's
rendered text, which mixes in a copy-icon glyph and inconsistent whitespace.

Refine is NOT part of the item link's own text -- FluxCP renders it as a
sibling text node ("+ 7 ") preceding the <a> inside the same <td>. The parser
matches the refine marker against the enclosing cell's full text, not the
link text.
"""
import math
import re

from bs4 import BeautifulSoup

from .models import Listing, MerchantPage

_RECORDS_RE = re.compile(r"total of ([\d,]+) record", re.I)
_ITEM_ID_RE = re.compile(r"[?&]id=(\d+)")
_REFINE_RE = re.compile(r"^\+\s*(\d+)\s+(.*)$")


def parse_price(text: str) -> int:
    return int(re.sub(r"[^\d]", "", text))


def total_pages(total_records: int, per_page: int = 20) -> int:
    return max(1, math.ceil(total_records / per_page))


def _find_merchant_table(soup):
    """Return the data table, or None. A None result means a valid FluxCP page
    with no listing table -- e.g. a page paginated past the last record. Callers
    treat that as end-of-data (empty page), not an error."""
    return soup.find("table", class_="horizontal-table")


def parse_merchant_page(html: str, kind: str) -> MerchantPage:
    if kind not in ("vendors", "buyers"):
        raise ValueError(f"kind must be vendors|buyers, got {kind!r}")
    soup = BeautifulSoup(html, "lxml")

    m = _RECORDS_RE.search(soup.get_text())
    total_records = int(m.group(1).replace(",", "")) if m else 0

    table = _find_merchant_table(soup)
    if table is None:
        # Past the last page (or an empty result set): no rows, no error.
        return MerchantPage(rows=[], total_records=total_records)

    rows: list[Listing] = []
    for tr in table.find_all("tr"):
        link = tr.find("a", href=_ITEM_ID_RE)
        if link is None:
            continue  # header row / spacer
        item_id = int(_ITEM_ID_RE.search(link["href"]).group(1))

        tds = tr.find_all("td")
        if not tds:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds]

        btn = tr.find("button", attrs={"data-map": True})
        if btn is not None:
            map_ = btn["data-map"]
            x, y = int(btn["data-x"]), int(btn["data-y"])
        else:
            map_, x, y = "", 0, 0

        name_td = link.find_parent("td")
        name_idx = tds.index(name_td)
        name_cell_text = cells[name_idx]

        refine, item_name = 0, name_cell_text
        rm = _REFINE_RE.match(name_cell_text)
        if rm:
            refine, item_name = int(rm.group(1)), rm.group(2).strip()

        # Cells after the item-name cell: amount then price (then cards for vendors).
        tail = cells[name_idx + 1:]
        amount = int(re.sub(r"[^\d]", "", tail[0]))
        price = parse_price(tail[1])
        cards = tail[2] if kind == "vendors" and len(tail) > 2 and tail[2] else "None"

        rows.append(
            Listing(
                merchant=cells[0],
                shop=cells[1] if len(cells) > 1 else "",
                map=map_,
                x=x,
                y=y,
                item_id=item_id,
                item_name=item_name,
                refine=refine if kind == "vendors" else 0,
                cards=cards if kind == "vendors" else "None",
                amount=amount,
                price=price,
            )
        )
    return MerchantPage(rows=rows, total_records=total_records)
