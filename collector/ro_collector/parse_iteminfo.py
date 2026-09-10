"""Parse the game client's itemInfo Lua into item_id -> description text.

the server's client ships System/itemInfo_pro.lub as PLAIN TEXT Lua (the .lub
extension lies). It is the authoritative in-game tooltip source — including
server custom effects the control panel never shows (e.g. Orc Archer Bow's
+50% with Steel Arrows). Entries look like:

    [1734] = {
        identifiedDisplayName = "Orc Archer Bow",
        identifiedDescriptionName = {
            "line one",
            "line ^RRGGBBwith color codes^000000",
        },
        ...
    },

We keep the ^RRGGBB codes — the dashboard tooltip renders them as colors.
Korean resource names are CP949; read the file with encoding="cp949",
errors="replace" (description lines are English and unaffected).
"""
import re

_ENTRY_HEAD = re.compile(r"^\s*\[(\d+)\]\s*=\s*\{", re.M)
_DESC = re.compile(r"(?<!un)identifiedDescriptionName\s*=\s*\{(.*?)\}", re.S)
_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def parse_item_info_lua(text: str) -> dict[int, str]:
    # Anchor on entry HEADERS only ("[id] = {" at line start) and treat each
    # entry as the slice up to the next header — closing-brace formats vary
    # between the translation file and appended custom blocks, so matching
    # the entry's closing brace is unreliable.
    heads = list(_ENTRY_HEAD.finditer(text))
    out: dict[int, str] = {}
    for i, m in enumerate(heads):
        item_id = int(m.group(1))
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        d = _DESC.search(body)
        if not d:
            continue
        lines = [s.replace('\\"', '"') for s in _STR.findall(d.group(1))]
        desc = "\n".join(lines).strip()
        if desc:
            out[item_id] = desc
    return out
