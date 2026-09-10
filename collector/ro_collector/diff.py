"""Snapshot diffing: disappeared/shrunk listings between consecutive complete
snapshots are recorded as probable sales — the market's demand signal."""
from collections import defaultdict
from dataclasses import dataclass

from .models import Listing


@dataclass(frozen=True)
class ProbableSale:
    item_id: int
    item_name: str
    refine: int
    cards: str
    price: int
    qty: int


def _aggregate(listings: list[Listing]) -> dict:
    agg: dict = defaultdict(lambda: [0, ""])
    for l in listings:
        key = (l.merchant, l.item_id, l.refine, l.cards, l.price)
        agg[key][0] += l.amount
        agg[key][1] = l.item_name
    return agg


def diff_snapshots(prev: list[Listing], curr: list[Listing]) -> list[ProbableSale]:
    prev_agg = _aggregate(prev)
    curr_agg = _aggregate(curr)
    sales = []
    for key, (prev_amt, item_name) in prev_agg.items():
        curr_amt = curr_agg.get(key, [0, ""])[0]
        if curr_amt < prev_amt:
            merchant, item_id, refine, cards, price = key
            sales.append(ProbableSale(item_id, item_name, refine, cards, price, prev_amt - curr_amt))
    return sales
