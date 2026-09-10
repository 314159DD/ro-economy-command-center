"""Server-side drop nerfs the CP does not show (Sleeper Great Nature case)."""
from ro_collector.overrides import apply_drop_overrides, load_drop_overrides


def test_apply_multiplies_matching_rates_only():
    drops = [
        {"monster_id": 1386, "item_id": 997, "item_name": "Great Nature", "rate": 100.0},
        {"monster_id": 1386, "item_id": 1056, "item_name": "Grit", "rate": 100.0},
    ]
    out = apply_drop_overrides(drops, {(1386, 997): 0.25})
    assert out[0]["rate"] == 25.0
    assert out[1]["rate"] == 100.0
    assert drops[0]["rate"] == 100.0  # originals untouched


def test_real_seed_contains_the_sleeper_nerf():
    ov = load_drop_overrides()
    assert ov[(1386, 997)] == 0.25


def test_no_overrides_is_a_passthrough():
    drops = [{"monster_id": 1, "item_id": 2, "item_name": "X", "rate": 5.0}]
    assert apply_drop_overrides(drops, {}) is drops
