"""Capture real pages as test fixtures. Run manually: needs collector/.env with RO_SESSION_COOKIE.

Usage (from collector/): .venv\\Scripts\\python scripts/capture_fixtures.py
"""
import pathlib
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[0].parent))
from ro_collector.config import load_settings  # noqa: E402
from ro_collector.http_client import USER_AGENT, RoClient  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def save(name: str, html: str) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(html, encoding="utf-8")
    print(f"saved {name} ({len(html):,} bytes)")


def main() -> None:
    s = load_settings()
    client = RoClient(s.session_cookie, s.throttle_seconds)
    client.ensure_authed()
    save("vendors_p1.html", client.get_page(module="merchant", action="vendors", p=1))
    save("buyers_p1.html", client.get_page(module="merchant", action="buyers", p=1))
    save("monster_index_p1.html", client.get_page(module="monster", p=1))
    save("monster_1206.html", client.get_page(module="monster", action="view", id=1206))
    wiki = requests.get(
        "https://example.com/wiki/Repeatable_Quests/", headers={"User-Agent": USER_AGENT}, timeout=30
    )
    wiki.raise_for_status()
    save("wiki_repeatable_quests.html", wiki.text)


if __name__ == "__main__":
    main()
