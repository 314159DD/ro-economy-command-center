"""Shared dataclasses for parsed CP data."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Listing:
    merchant: str
    shop: str
    map: str
    x: int
    y: int
    item_id: int
    item_name: str
    refine: int
    cards: str
    amount: int
    price: int


@dataclass(frozen=True)
class MerchantPage:
    rows: list  # list[Listing]
    total_records: int


@dataclass(frozen=True)
class Drop:
    item_id: int
    item_name: str
    rate: float  # percent, server-true (multipliers applied)


@dataclass(frozen=True)
class Monster:
    id: int
    name: str
    level: int | None
    hp: int | None
    drops: list  # list[Drop]


@dataclass(frozen=True)
class TurnInQuest:
    form: str  # 'item' | 'hunt'
    npc: str
    location: str
    min_level: int
    max_level: int
    target_name: str  # item name (item form) or monster name (hunt form)
    qty: int          # items required, or monsters per smallest hunt (50)
    base_exp: int
    job_exp: int
