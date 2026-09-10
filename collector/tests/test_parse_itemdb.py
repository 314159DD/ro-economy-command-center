"""Parse Hercules item_db.conf into item_id -> NPC sell price."""
from ro_collector.parse_itemdb import parse_npc_sell

SAMPLE = '''item_db: (
{
	Id: 501
	AegisName: "Red_Potion"
	Name: "Red Potion"
	Buy: 50
	Weight: 70
},
{
	Id: 998
	AegisName: "Iron"
	Name: "Iron"
	Buy: 100
	Weight: 50
},
{
	Id: 700
	AegisName: "Explicit_Sell"
	Name: "Explicit Sell"
	Buy: 100
	Sell: 80
},
{
	Id: 701
	AegisName: "No_Price"
	Name: "No Price"
	Weight: 10
}
)
'''


def test_sell_defaults_to_half_buy():
    out = parse_npc_sell(SAMPLE)
    assert out[501] == 25
    assert out[998] == 50


def test_explicit_sell_wins():
    assert parse_npc_sell(SAMPLE)[700] == 80


def test_items_without_price_are_skipped():
    assert 701 not in parse_npc_sell(SAMPLE)
