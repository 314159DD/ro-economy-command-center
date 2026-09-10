"""Parse the game client's itemInfo Lua (System/itemInfo_pro.lub — plain text
despite the extension) into item_id -> in-game description text."""
from ro_collector.parse_iteminfo import parse_item_info_lua

SAMPLE = '''tbl = {
	[1734] = {
		unidentifiedDisplayName = "Bow",
		unidentifiedResourceName = "\xbf\xc0\xba\xea",
		unidentifiedDescriptionName = { "Unknown Item, can be identified by using a ^6666CCMagnifier^000000." },
		identifiedDisplayName = "Orc Archer Bow",
		identifiedResourceName = "\xbf\xc0\xba\xea",
		identifiedDescriptionName = {
			"A large, powerful bow used by Orc Archers.",
			"Randomly a defeated monster will drop ^6666CCSteel Arrow^000000.",
			"Class:^6666CC Bow^000000"
		},
		slotCount = 0,
		ClassNum = 11
	},
	[909] = {
		identifiedDisplayName = "Jellopy",
		identifiedDescriptionName = {
			"A small crystallization created by some monsters."
		},
		slotCount = 0,
		ClassNum = 0
	},
	[999] = {
		identifiedDisplayName = "No Desc Item",
		identifiedDescriptionName = {},
		slotCount = 0
	}
}
'''


def test_parses_descriptions_by_item_id():
    out = parse_item_info_lua(SAMPLE)
    assert out[1734] == (
        "A large, powerful bow used by Orc Archers.\n"
        "Randomly a defeated monster will drop ^6666CCSteel Arrow^000000.\n"
        "Class:^6666CC Bow^000000"
    )
    assert out[909] == "A small crystallization created by some monsters."
    assert 999 not in out  # empty description -> skipped


def test_ignores_unidentified_description():
    out = parse_item_info_lua(SAMPLE)
    assert "Magnifier" not in out[1734]


def test_parses_real_client_file_if_present():
    import pathlib
    lub = pathlib.Path(r"C:\Gamez\the server\System\itemInfo_pro.lub")
    if not lub.exists():
        return  # other machines: covered by SAMPLE tests
    out = parse_item_info_lua(lub.read_text(encoding="cp949", errors="replace"))
    assert len(out) > 14_000  # the client file has ~15.5k item entries
    assert "Increases long range physical attacks by 50%" in out[1734]
