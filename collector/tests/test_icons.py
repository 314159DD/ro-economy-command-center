"""Icon cache: download the server CP item icons once, embed as data URIs."""
from ro_collector.icons import ensure_icons, icon_data_uris


def test_ensure_icons_downloads_missing_and_caches(tmp_path):
    fetched = []

    def fake_fetch(item_id):
        fetched.append(item_id)
        return b"\x89PNG fake" if item_id != 404404 else None

    ensure_icons([1734, 909, 404404], tmp_path, fetch=fake_fetch)
    assert (tmp_path / "1734.png").read_bytes() == b"\x89PNG fake"
    assert (tmp_path / "909.png").exists()
    assert not (tmp_path / "404404.png").exists()  # miss -> no file
    assert sorted(fetched) == [909, 1734, 404404]

    # second run: cached files are not re-fetched (missing 404404 is retried)
    fetched.clear()
    ensure_icons([1734, 909, 404404], tmp_path, fetch=fake_fetch)
    assert fetched == [404404]


def test_icon_data_uris_builds_base64_map(tmp_path):
    (tmp_path / "1734.png").write_bytes(b"\x89PNG fake")
    uris = icon_data_uris([1734, 999999], tmp_path)
    assert uris[1734].startswith("data:image/png;base64,")
    assert 999999 not in uris  # no cached icon -> no entry
