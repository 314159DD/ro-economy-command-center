"""Thin Postgres I/O layer. All logic lives elsewhere; this only moves rows."""
import psycopg
from psycopg.rows import dict_row

from .models import Listing, Monster, TurnInQuest


class Store:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _conn(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def init_schema(self, schema_sql: str) -> None:
        with self._conn() as conn:
            conn.execute(schema_sql)

    def insert_snapshot(self, kind: str, total_records: int, complete: bool, rows: list[Listing]) -> int:
        table = "listings" if kind == "vendors" else "buy_orders"
        with self._conn() as conn:
            snap = conn.execute(
                "INSERT INTO snapshots (kind, total_records, complete) VALUES (%s,%s,%s) RETURNING id",
                (kind, total_records, complete),
            ).fetchone()["id"]
            with conn.cursor() as cur:
                if kind == "vendors":
                    cur.executemany(
                        f"INSERT INTO {table} (snapshot_id,merchant,shop,map,x,y,item_id,item_name,refine,cards,amount,price)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(snap, r.merchant, r.shop, r.map, r.x, r.y, r.item_id, r.item_name,
                          r.refine, r.cards, r.amount, r.price) for r in rows],
                    )
                else:
                    cur.executemany(
                        f"INSERT INTO {table} (snapshot_id,merchant,shop,map,x,y,item_id,item_name,amount,asking_price)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(snap, r.merchant, r.shop, r.map, r.x, r.y, r.item_id, r.item_name,
                          r.amount, r.price) for r in rows],
                    )
            return snap

    def latest_complete_snapshot_ids(self, kind: str, n: int = 2) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM snapshots WHERE kind=%s AND complete ORDER BY taken_at DESC LIMIT %s",
                (kind, n),
            ).fetchall()
            return [r["id"] for r in rows]

    def listings_for_snapshot(self, snapshot_id: int) -> list[Listing]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM listings WHERE snapshot_id=%s", (snapshot_id,)).fetchall()
            return [
                Listing(r["merchant"], r["shop"], r["map"], r["x"], r["y"], r["item_id"],
                        r["item_name"], r["refine"], r["cards"], r["amount"], r["price"])
                for r in rows
            ]

    def pair_already_diffed(self, prev_id: int, curr_id: int) -> bool:
        """True if probable_sales already has rows for this snapshot pair."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM probable_sales WHERE prev_snapshot_id=%s AND curr_snapshot_id=%s) AS seen",
                (prev_id, curr_id),
            ).fetchone()
            return row["seen"]

    def insert_probable_sales(self, sales: list, prev_id: int, curr_id: int) -> None:
        """Rows are duck-typed ProbableSale objects (defined in diff.py, Task 8)."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO probable_sales (item_id,item_name,refine,cards,price,qty,prev_snapshot_id,curr_snapshot_id)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                [(s.item_id, s.item_name, s.refine, s.cards, s.price, s.qty, prev_id, curr_id) for s in sales],
            )

    def upsert_monsters(self, monsters: list[Monster]) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            for m in monsters:
                cur.execute(
                    "INSERT INTO monsters (id,name,level,hp) VALUES (%s,%s,%s,%s)"
                    " ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, level=EXCLUDED.level, hp=EXCLUDED.hp",
                    (m.id, m.name, m.level, m.hp),
                )
                for d in m.drops:
                    cur.execute(
                        "INSERT INTO drops (monster_id,item_id,item_name,rate) VALUES (%s,%s,%s,%s)"
                        " ON CONFLICT (monster_id,item_id) DO UPDATE SET rate=EXCLUDED.rate, item_name=EXCLUDED.item_name",
                        (m.id, d.item_id, d.item_name, d.rate),
                    )
                    cur.execute(
                        "INSERT INTO items (id,name) VALUES (%s,%s) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name",
                        (d.item_id, d.item_name),
                    )

    def upsert_item_info(self, info: dict) -> None:
        """info: parse_item.parse_item_page output. Keeps an existing
        description (that column is owned by the client-file enrich)."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO items (id,name,item_type,weight,atk,defense,slots,equip_level,npc_sell,info_fetched_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())"
                " ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,"
                " item_type=EXCLUDED.item_type, weight=EXCLUDED.weight, atk=EXCLUDED.atk,"
                " defense=EXCLUDED.defense, slots=EXCLUDED.slots, equip_level=EXCLUDED.equip_level,"
                " npc_sell=EXCLUDED.npc_sell, info_fetched_at=now()",
                (info["item_id"], info["name"], info["item_type"],
                 info["weight"], info["atk"], info["defense"], info["slots"], info["equip_level"],
                 info.get("npc_sell")),
            )

    def upsert_item_descriptions(self, descriptions: dict[int, str]) -> None:
        """Batch: descriptions from the game client's itemInfo (enrich_iteminfo).
        One connection for the whole load — row-at-a-time over Neon is ~100x slower.
        Doesn't require the items to exist yet; names backfilled by other crawls."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO items (id,name,description,info_fetched_at) VALUES (%s,%s,%s,now())"
                " ON CONFLICT (id) DO UPDATE SET description=EXCLUDED.description, info_fetched_at=now()",
                [(item_id, f"Item #{item_id}", desc) for item_id, desc in descriptions.items()],
            )

    def item_ids_missing_info(self, ids: list[int]) -> list[int]:
        """Which of these item ids have no server-true NPC sell price yet
        (the CP crawl's job; descriptions come from the client file)."""
        if not ids:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM items WHERE id = ANY(%s) AND npc_sell IS NOT NULL", (list(ids),)
            ).fetchall()
        have = {r["id"] for r in rows}
        return sorted(i for i in set(ids) if i not in have)

    def price_history(self, max_snapshots: int = 30) -> dict:
        """item_id -> [[date, vendor_low, best_bid], ...] (comparable listings
        only), one point per snapshot day, capped at the latest N snapshots."""
        with self._conn() as conn:
            vrows = conn.execute(
                "WITH vs AS (SELECT id, taken_at FROM snapshots WHERE kind='vendors' AND complete"
                "            ORDER BY taken_at DESC LIMIT %s)"
                " SELECT l.item_id, to_char(vs.taken_at, 'YYYY-MM-DD') AS d, MIN(l.price) AS low"
                " FROM listings l JOIN vs ON vs.id = l.snapshot_id"
                " WHERE l.refine = 0 AND l.cards = 'None'"
                " GROUP BY l.item_id, d", (max_snapshots,)).fetchall()
            brows = conn.execute(
                "WITH bs AS (SELECT id, taken_at FROM snapshots WHERE kind='buyers' AND complete"
                "            ORDER BY taken_at DESC LIMIT %s)"
                " SELECT b.item_id, to_char(bs.taken_at, 'YYYY-MM-DD') AS d, MAX(b.asking_price) AS bid"
                " FROM buy_orders b JOIN bs ON bs.id = b.snapshot_id"
                " GROUP BY b.item_id, d", (max_snapshots,)).fetchall()
        low = {(r["item_id"], r["d"]): r["low"] for r in vrows}
        bid = {(r["item_id"], r["d"]): r["bid"] for r in brows}
        out: dict[int, list] = {}
        for item_id, d in sorted(set(low) | set(bid), key=lambda k: (k[0], k[1])):
            out.setdefault(item_id, []).append([d, low.get((item_id, d)), bid.get((item_id, d))])
        return out

    def listings_history(self, max_snapshots: int = 14) -> list[dict]:
        """Comparable listings across the latest N vendor snapshots, with the
        snapshot date - powers merchant profiling."""
        with self._conn() as conn:
            rows = conn.execute(
                "WITH vs AS (SELECT id, taken_at FROM snapshots WHERE kind='vendors' AND complete"
                "            ORDER BY taken_at DESC LIMIT %s)"
                " SELECT l.merchant, l.shop, l.map, l.x, l.y, l.item_id, l.price, l.amount,"
                "        to_char(vs.taken_at, 'YYYY-MM-DD') AS d"
                " FROM listings l JOIN vs ON vs.id = l.snapshot_id"
                " WHERE l.refine = 0 AND l.cards = 'None'", (max_snapshots,)).fetchall()
        return [dict(r) for r in rows]

    def upsert_npc_sell(self, prices: dict[int, int]) -> None:
        """Batch: mainline/wiki NPC sell prices — FILL GAPS ONLY. The CP crawl
        (enrich_items) writes server-true values and must never be overwritten
        by mainline guesses (Royal Jelly: 3,500 mainline vs 2,750 on this server,
        undocumented)."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO items (id,name,npc_sell) VALUES (%s,%s,%s)"
                " ON CONFLICT (id) DO UPDATE SET npc_sell=EXCLUDED.npc_sell"
                " WHERE items.npc_sell IS NULL",
                [(item_id, f"Item #{item_id}", sell) for item_id, sell in prices.items()],
            )

    def latest_snapshot_ts(self) -> int | None:
        """Epoch seconds of the newest complete vendors snapshot (data age)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT extract(epoch from max(taken_at))::bigint AS ts"
                " FROM snapshots WHERE kind='vendors' AND complete").fetchone()
        return row["ts"]

    def npc_sell_map(self) -> dict[int, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT id, npc_sell FROM items WHERE npc_sell IS NOT NULL").fetchall()
        return {r["id"]: r["npc_sell"] for r in rows}

    def item_info_all(self) -> dict:
        """item_id -> {description, item_type, weight, atk, defense, slots, equip_level}."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, description, item_type, weight, atk, defense, slots, equip_level"
                " FROM items WHERE info_fetched_at IS NOT NULL"
            ).fetchall()
        return {r["id"]: dict(r) for r in rows}

    def upsert_monster_meta(self, meta) -> None:
        """meta: duck-typed MonsterMeta (parse_ragnapi.MonsterMeta)."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO monster_meta"
                " (monster_id,name,size,race,element,element_power,level,hp,flee,hit,def,mdef,aspd,base_exp,job_exp,best_element,boss_class)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (monster_id) DO UPDATE SET name=EXCLUDED.name, size=EXCLUDED.size,"
                " race=EXCLUDED.race, element=EXCLUDED.element, element_power=EXCLUDED.element_power,"
                " level=EXCLUDED.level, hp=EXCLUDED.hp, flee=EXCLUDED.flee, hit=EXCLUDED.hit,"
                " def=EXCLUDED.def, mdef=EXCLUDED.mdef, aspd=EXCLUDED.aspd, base_exp=EXCLUDED.base_exp,"
                " job_exp=EXCLUDED.job_exp, best_element=EXCLUDED.best_element, boss_class=EXCLUDED.boss_class",
                (meta.monster_id, meta.name, meta.size, meta.race, meta.element, meta.element_power,
                 meta.level, meta.hp, meta.flee, meta.hit, meta.def_, meta.mdef, meta.aspd,
                 meta.base_exp, meta.job_exp, meta.best_element, meta.boss_class),
            )

    def replace_spawns(self, monster_id: int, spawns: list) -> None:
        """Replace all spawn rows for one monster. spawns: duck-typed MonsterSpawn list."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM monster_spawns WHERE monster_id=%s", (monster_id,))
            cur.executemany(
                "INSERT INTO monster_spawns (monster_id,map_name,map_number,amount,map_type)"
                " VALUES (%s,%s,%s,%s,%s) ON CONFLICT (monster_id,map_name,map_number) DO NOTHING",
                [(s.monster_id, s.map_name, s.map_number, s.amount, s.map_type) for s in spawns],
            )

    def farm_spot_by_name(self, name: str) -> dict | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM farm_spots WHERE name=%s", (name,)).fetchone()

    def calibrate_spot(self, name: str, kills_per_hour: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE farm_spots SET kills_per_hour=%s, calibrated=true WHERE name=%s",
                (kills_per_hour, name),
            )
            return cur.rowcount > 0

    def insert_farm_session(self, spot_id: int, played_minutes: int, loot: dict) -> None:
        import json
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO farm_sessions (spot_id, played_minutes, loot) VALUES (%s,%s,%s)",
                (spot_id, played_minutes, json.dumps(loot)),
            )

    def monster_ids(self) -> list[int]:
        with self._conn() as conn:
            return [r["id"] for r in conn.execute("SELECT id FROM monsters ORDER BY id").fetchall()]

    def monster_meta_all(self) -> dict:
        with self._conn() as conn:
            return {r["monster_id"]: r for r in conn.execute("SELECT * FROM monster_meta").fetchall()}

    def best_spawns(self) -> dict:
        """monster_id -> densest spawn row (highest amount)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ON (monster_id) monster_id, map_name, map_number, amount, map_type"
                " FROM monster_spawns ORDER BY monster_id, amount DESC"
            ).fetchall()
            return {r["monster_id"]: r for r in rows}

    def replace_turnins(self, quests: list[TurnInQuest], npc_purchasable: dict[str, str]) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM quest_turnins")
            cur.executemany(
                "INSERT INTO quest_turnins (form,npc,location,min_level,max_level,target_name,qty,base_exp,job_exp,npc_purchase_note,player_vendable)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(q.form, q.npc, q.location, q.min_level, q.max_level, q.target_name, q.qty,
                  q.base_exp, q.job_exp, npc_purchasable.get(q.target_name),
                  q.target_name != "Antelope Horn") for q in quests],
            )

    def resolve_turnin_item_ids(self) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE quest_turnins q SET item_id = i.id FROM items i"
                " WHERE q.form='item' AND q.item_id IS NULL AND lower(i.name)=lower(q.target_name)"
            )
            return cur.rowcount

    def upsert_farm_spots(self, rows: list[dict]) -> None:
        """Upserts by name and deliberately does NOT delete stale rows — farm_sessions FK makes deletion unsafe."""
        with self._conn() as conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    "INSERT INTO farm_spots (name,map,monster_ids,min_level,kills_per_hour,arrows_per_hour,arrow_price,notes)"
                    " VALUES (%(name)s,%(map)s,%(monster_ids)s,%(min_level)s,%(kills_per_hour)s,%(arrows_per_hour)s,%(arrow_price)s,%(notes)s)"
                    " ON CONFLICT (name) DO UPDATE SET map=EXCLUDED.map, monster_ids=EXCLUDED.monster_ids,"
                    " min_level=EXCLUDED.min_level, kills_per_hour=EXCLUDED.kills_per_hour,"
                    " arrows_per_hour=EXCLUDED.arrows_per_hour, arrow_price=EXCLUDED.arrow_price, notes=EXCLUDED.notes",
                    r,
                )

    # ---- read helpers for scoring/shortlist ----

    def latest_listings(self) -> list[Listing]:
        ids = self.latest_complete_snapshot_ids("vendors", 1)
        return self.listings_for_snapshot(ids[0]) if ids else []

    def latest_buy_orders(self) -> list[Listing]:
        ids = self.latest_complete_snapshot_ids("buyers", 1)
        if not ids:
            return []
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM buy_orders WHERE snapshot_id=%s", (ids[0],)).fetchall()
            return [
                Listing(r["merchant"], r["shop"], r["map"], r["x"], r["y"], r["item_id"],
                        r["item_name"], 0, "None", r["amount"], r["asking_price"])
                for r in rows
            ]

    def sales_since(self, days: int) -> list[dict]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT item_id, refine, cards, price, qty, inferred_at FROM probable_sales"
                " WHERE inferred_at > now() - make_interval(days => %s)", (days,),
            ).fetchall()

    def all_drops(self) -> list[dict]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT d.monster_id, m.name AS monster_name, d.item_id, d.item_name, d.rate::float AS rate"
                " FROM drops d JOIN monsters m ON m.id=d.monster_id"
            ).fetchall()

    def farm_spots(self) -> list[dict]:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM farm_spots ORDER BY id").fetchall()

    def turnins(self) -> list[dict]:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM quest_turnins ORDER BY id").fetchall()

    # ---- trade ledger / balance tracking ----

    def item_name_by_id(self, item_id: int) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT name FROM items WHERE id=%s", (item_id,)).fetchone()
        return row["name"] if row else None

    def items_by_name(self, name: str) -> list[dict]:
        with self._conn() as conn:
            return conn.execute("SELECT id, name FROM items WHERE name ILIKE %s", (name,)).fetchall()

    def insert_trade(self, item_id, item_name, side, qty, price, strategy, note=None):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO trades (item_id,item_name,side,qty,price,strategy,note) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (item_id, item_name, side, qty, price, strategy, note))

    def trades_all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT item_id, item_name, side, qty, price, strategy FROM trades ORDER BY ts").fetchall()
        return [dict(r) for r in rows]

    def insert_balance(self, zeny: int) -> None:
        with self._conn() as conn:
            conn.execute("INSERT INTO balances (zeny) VALUES (%s)", (zeny,))

    def balances_all(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT to_char(ts, 'YYYY-MM-DD HH24:MI') AS d, zeny FROM balances ORDER BY ts").fetchall()
        return [[r["d"], r["zeny"]] for r in rows]
