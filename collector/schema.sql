CREATE TABLE IF NOT EXISTS snapshots (
  id            BIGSERIAL PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('vendors','buyers')),
  taken_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  complete      BOOLEAN NOT NULL DEFAULT false,
  total_records INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS listings (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  merchant    TEXT NOT NULL,
  shop        TEXT NOT NULL DEFAULT '',
  map         TEXT NOT NULL DEFAULT '',
  x           INT NOT NULL DEFAULT 0,
  y           INT NOT NULL DEFAULT 0,
  item_id     INT NOT NULL,
  item_name   TEXT NOT NULL,
  refine      INT NOT NULL DEFAULT 0,
  cards       TEXT NOT NULL DEFAULT 'None',
  amount      INT NOT NULL,
  price       BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS listings_snap_item ON listings (snapshot_id, item_id);

CREATE TABLE IF NOT EXISTS buy_orders (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  merchant    TEXT NOT NULL,
  shop        TEXT NOT NULL DEFAULT '',
  map         TEXT NOT NULL DEFAULT '',
  x           INT NOT NULL DEFAULT 0,
  y           INT NOT NULL DEFAULT 0,
  item_id     INT NOT NULL,
  item_name   TEXT NOT NULL,
  amount      INT NOT NULL,
  asking_price BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS buy_orders_snap_item ON buy_orders (snapshot_id, item_id);

CREATE TABLE IF NOT EXISTS probable_sales (
  id               BIGSERIAL PRIMARY KEY,
  item_id          INT NOT NULL,
  item_name        TEXT NOT NULL,
  refine           INT NOT NULL,
  cards            TEXT NOT NULL,
  price            BIGINT NOT NULL,
  qty              INT NOT NULL,
  prev_snapshot_id BIGINT NOT NULL REFERENCES snapshots(id),
  curr_snapshot_id BIGINT NOT NULL REFERENCES snapshots(id),
  inferred_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS probable_sales_item ON probable_sales (item_id, inferred_at);

CREATE TABLE IF NOT EXISTS monsters (
  id    INT PRIMARY KEY,
  name  TEXT NOT NULL,
  level INT,
  hp    BIGINT
);

CREATE TABLE IF NOT EXISTS drops (
  monster_id INT NOT NULL REFERENCES monsters(id) ON DELETE CASCADE,
  item_id    INT NOT NULL,
  item_name  TEXT NOT NULL,
  rate       NUMERIC(8,4) NOT NULL,
  PRIMARY KEY (monster_id, item_id)
);

CREATE TABLE IF NOT EXISTS items (
  id   INT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS farm_spots (
  id              SERIAL PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE,
  map             TEXT NOT NULL,
  monster_ids     INT[] NOT NULL,
  min_level       INT NOT NULL,
  kills_per_hour  INT NOT NULL,
  arrows_per_hour INT NOT NULL DEFAULT 2400,
  arrow_price     INT NOT NULL DEFAULT 2,
  notes           TEXT NOT NULL DEFAULT '',
  calibrated      BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS farm_sessions (
  id             BIGSERIAL PRIMARY KEY,
  spot_id        INT NOT NULL REFERENCES farm_spots(id),
  played_minutes INT NOT NULL,
  loot           JSONB NOT NULL DEFAULT '{}',
  logged_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quest_turnins (
  id               SERIAL PRIMARY KEY,
  form             TEXT NOT NULL CHECK (form IN ('item','hunt')),
  npc              TEXT NOT NULL,
  location         TEXT NOT NULL,
  min_level        INT NOT NULL,
  max_level        INT NOT NULL,
  target_name      TEXT NOT NULL,
  item_id          INT,
  qty              INT NOT NULL,
  base_exp         BIGINT NOT NULL,
  job_exp          BIGINT NOT NULL,
  npc_purchase_note TEXT,
  player_vendable  BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS monster_meta (
  monster_id    INT PRIMARY KEY REFERENCES monsters(id) ON DELETE CASCADE,
  name          TEXT NOT NULL DEFAULT '',
  size          TEXT NOT NULL DEFAULT '',
  race          TEXT NOT NULL DEFAULT '',
  element       TEXT NOT NULL DEFAULT '',
  element_power INT NOT NULL DEFAULT 0,
  level         INT,
  hp            BIGINT,
  flee          INT,
  hit           INT,
  def           INT,
  mdef          INT,
  aspd          NUMERIC(6,2),
  base_exp      BIGINT,
  job_exp       BIGINT,
  best_element  TEXT NOT NULL DEFAULT '',
  boss_class    TEXT NOT NULL DEFAULT 'normal'
);

ALTER TABLE monster_meta ADD COLUMN IF NOT EXISTS boss_class TEXT NOT NULL DEFAULT 'normal';

CREATE TABLE IF NOT EXISTS monster_spawns (
  monster_id INT NOT NULL REFERENCES monsters(id) ON DELETE CASCADE,
  map_name   TEXT NOT NULL,
  map_number INT NOT NULL DEFAULT 0,
  amount     INT NOT NULL,
  map_type   TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (monster_id, map_name, map_number)
);
CREATE INDEX IF NOT EXISTS monster_spawns_mid ON monster_spawns (monster_id);

-- Item info from the CP item view pages (module=item&action=view) — the
-- in-game description text + basic stats, for the dashboard tooltip.
-- (CREATE TABLE IF NOT EXISTS won't add columns to an existing table.)
ALTER TABLE items ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS item_type TEXT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS weight INT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS atk INT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS defense INT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS slots INT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS equip_level INT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS info_fetched_at TIMESTAMPTZ;

-- NPC sell price (Hercules mainline; refined by CP crawls) for Overcharge flips
ALTER TABLE items ADD COLUMN IF NOT EXISTS npc_sell INT;

CREATE TABLE IF NOT EXISTS trades (
  id        SERIAL PRIMARY KEY,
  ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
  item_id   INT,
  item_name TEXT NOT NULL,
  side      TEXT NOT NULL,
  qty       INT NOT NULL,
  price     BIGINT NOT NULL,
  strategy  TEXT NOT NULL DEFAULT 'other',
  note      TEXT
);

CREATE TABLE IF NOT EXISTS balances (
  id   SERIAL PRIMARY KEY,
  ts   TIMESTAMPTZ NOT NULL DEFAULT now(),
  zeny BIGINT NOT NULL
);
