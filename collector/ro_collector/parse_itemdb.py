"""Parse Hercules pre-re item_db.conf into item_id -> NPC sell price.

NPC sell = explicit Sell, else floor(Buy / 2) (the Hercules default). These
are MAINLINE values - server customs may differ; the CP item pages show the
server-true Sell and can refine this later via the enrich_items crawl.
"""
import re

_ID = re.compile(r"^\tId: (\d+)$", re.M)
_BUY = re.compile(r"^\tBuy: (\d+)$", re.M)
_SELL = re.compile(r"^\tSell: (\d+)$", re.M)
_NAME = re.compile(r'^\tName: "([^"]+)"$', re.M)


def _entries(text: str):
    heads = list(_ID.finditer(text))
    for i, m in enumerate(heads):
        yield int(m.group(1)), text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]


def parse_npc_sell(text: str) -> dict[int, int]:
    out: dict[int, int] = {}
    for item_id, body in _entries(text):
        sell = _SELL.search(body)
        buy = _BUY.search(body)
        if sell:
            out[item_id] = int(sell.group(1))
        elif buy:
            out[item_id] = int(buy.group(1)) // 2
    return out


def parse_item_names(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for item_id, body in _entries(text):
        name = _NAME.search(body)
        if name:
            out[item_id] = name.group(1)
    return out
