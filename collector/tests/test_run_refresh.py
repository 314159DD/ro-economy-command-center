from ro_collector import run_refresh
from ro_collector.models import Drop, Monster

INDEX_HTML = """
<html><body><p>Total of 2 records</p>
<table class="horizontal-table">
<tr>
  <td><a href="?module=monster&amp;action=view&amp;id=1001" class="link-to-monster">1001</a></td>
  <td></td><td>Poring</td><td>1</td><td>50</td><td>Small</td><td>Plant</td><td>Water</td><td>2</td><td>1</td>
</tr>
<tr>
  <td><a href="?module=monster&amp;action=view&amp;id=1002" class="link-to-monster">1002</a></td>
  <td></td><td>Ghost</td><td>5</td><td>999</td><td>Medium</td><td>Undead</td><td>Ghost</td><td>10</td><td>5</td>
</tr>
</table></body></html>
"""

VIEW_HTML_1001 = """
<html><body>
<table class="vertical-table">
<tr><td>Name</td><td>PoringView</td></tr>
<tr><td>Level</td><td>1</td></tr>
</table>
<table class="vertical-table">
<tr><th>Item ID</th><th>Item</th><th>Rate</th></tr>
<tr>
  <td><a href="?module=item&amp;action=view&amp;id=909">909</a></td><td></td><td>Jellopy</td><td>70%</td>
</tr>
</table>
</body></html>
"""

WIKI_HTML = """
<html><body>
<table>
<tr><th>NPC</th><th>Location</th><th>Min Level</th><th>Max Level</th><th>Items</th>
<th>Base EXP</th><th>Job EXP</th><th>Base EXP Per Item</th><th>Job EXP Per Item</th></tr>
<tr>
  <td>TestNPC</td><td>TestLoc</td><td>5</td><td>10</td><td>3 Widget</td>
  <td>100</td><td>50</td><td>33</td><td>16</td>
</tr>
</table>
<table>
<tr><th>NPC</th><th>Location</th><th>Min Level</th><th>Max Level</th><th>Monster</th>
<th>Base EXP</th><th>Job EXP</th><th>Base EXP Per Monster</th><th>Job EXP Per Monster</th></tr>
<tr>
  <td>HuntNPC</td><td>HuntLoc</td><td>20</td><td>30</td><td>TestMonster*</td>
  <td>5000</td><td>200</td><td>100</td><td>4</td>
</tr>
</table>
</body></html>
"""


class FakeClient:
    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.calls = []

    def get_page(self, **params):
        self.calls.append(params)
        if params.get("action") == "view":
            mid = params["id"]
            if mid in self.fail_ids:
                raise RuntimeError("boom")
            if mid == 1001:
                return VIEW_HTML_1001
            raise AssertionError(f"unexpected view fetch for {mid}")
        return INDEX_HTML  # single index page only (total=2 -> 1 page)


class FakeStore:
    def __init__(self):
        self.upsert_calls = []
        self.turnins = None
        self.npc_purchasable = None
        self.resolve_called = False

    def upsert_monsters(self, batch):
        self.upsert_calls.append(list(batch))

    def replace_turnins(self, quests, npc_purchasable):
        self.turnins = quests
        self.npc_purchasable = npc_purchasable

    def resolve_turnin_item_ids(self):
        self.resolve_called = True
        return 3


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _patch_wiki(monkeypatch, html=WIKI_HTML):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers, timeout))
        return FakeResponse(html)

    monkeypatch.setattr(run_refresh.requests, "get", fake_get)
    return calls


def test_run_merges_index_stats_with_view_drops(monkeypatch):
    _patch_wiki(monkeypatch)
    client = FakeClient(fail_ids={1002})
    store = FakeStore()

    run_refresh.run(client, store)

    upserted = [m for batch in store.upsert_calls for m in batch]
    assert len(upserted) == 1
    m = upserted[0]
    assert m == Monster(
        id=1001,
        name="PoringView",  # view name wins over index name
        level=1,            # from index
        hp=50,              # from index (view page has no hp)
        drops=[Drop(item_id=909, item_name="Jellopy", rate=70.0)],
    )


def test_failing_monster_view_is_skipped_without_aborting(monkeypatch):
    _patch_wiki(monkeypatch)
    client = FakeClient(fail_ids={1002})
    store = FakeStore()

    run_refresh.run(client, store)  # should not raise

    upserted_ids = {m.id for batch in store.upsert_calls for m in batch}
    assert upserted_ids == {1001}
    assert 1002 not in upserted_ids


def test_turnins_stored_and_resolved(monkeypatch):
    wiki_calls = _patch_wiki(monkeypatch)
    client = FakeClient(fail_ids={1002})
    store = FakeStore()

    run_refresh.run(client, store)

    assert len(wiki_calls) == 1
    assert wiki_calls[0][0] == run_refresh.WIKI_URL
    assert store.turnins is not None
    assert len(store.turnins) == 2
    forms = {q.form for q in store.turnins}
    assert forms == {"item", "hunt"}
    assert store.npc_purchasable is run_refresh.NPC_PURCHASABLE
    assert store.resolve_called is True
