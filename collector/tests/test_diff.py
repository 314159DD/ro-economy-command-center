from ro_collector.diff import diff_snapshots
from ro_collector.models import Listing


def L(merchant="M", item_id=501, name="Red Potion", refine=0, cards="None", amount=10, price=40):
    return Listing(merchant, "shop", "prt_mk", 100, 100, item_id, name, refine, cards, amount, price)


def test_vanished_listing_is_full_sale():
    sales = diff_snapshots([L(amount=10)], [])
    assert len(sales) == 1
    assert (sales[0].item_id, sales[0].qty, sales[0].price) == (501, 10, 40)


def test_decreased_amount_is_partial_sale():
    sales = diff_snapshots([L(amount=10)], [L(amount=3)])
    assert len(sales) == 1
    assert sales[0].qty == 7


def test_unchanged_and_new_listings_produce_nothing():
    assert diff_snapshots([L(amount=5)], [L(amount=5)]) == []
    assert diff_snapshots([], [L(amount=5)]) == []
    assert diff_snapshots([L(amount=3)], [L(amount=9)]) == []  # restock, not a sale


def test_same_item_different_price_are_distinct_keys():
    prev = [L(price=40, amount=5), L(price=50, amount=5)]
    curr = [L(price=50, amount=5)]
    sales = diff_snapshots(prev, curr)
    assert len(sales) == 1
    assert sales[0].price == 40 and sales[0].qty == 5


def test_duplicate_keys_aggregate_amounts():
    prev = [L(amount=3), L(amount=4)]  # same merchant/item/price twice
    curr = [L(amount=2)]
    sales = diff_snapshots(prev, curr)
    assert len(sales) == 1
    assert sales[0].qty == 5  # 7 -> 2
