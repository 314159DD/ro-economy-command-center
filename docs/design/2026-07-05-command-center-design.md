# Ragnarok Online Economy Command Center — Design Spec

**Date:** 2026-07-05
**Status:** Approved design, pre-implementation

## Goal

Get the player (72 Sniper on this server) to 1 billion zeny the fastest way, via an economy
intelligence tool with two pillars plus an EXP progression loop:

1. **Grind ranking** — server drop tables × live market prices × kill speed →
   "point the Sniper here tonight."
2. **Market intelligence** — daily full-market snapshots → demand gaps, scarcity,
   flips, buyer-order arbitrage. Information asymmetry is the real edge: nobody
   else on the server has daily snapshots with sell-through history.
3. **EXP loop** — zeny converts to EXP via repeatable turn-in quests (buy mats off
   the market). Leveling unlocks better zeny/hr spots. The tool models the whole
   loop: grind → buy cheapest EXP → unlock better spots → repeat, shifting weight
   into flips as capital grows.

Strategy verdict (agreed): grinding is capital formation; flips/arbitrage compound
and are the long-term engine. Week-1 snapshot diffs empirically answer "how much
zeny moves on this server per day," which sets the realistic 1B timeline.

## Server facts

- the server — Hercules, Classic Pre-renewal, Episode 13.1. Max 99/70.
- Rates x5/x5/x5 (weekend base/job x7.5). Normal cards 0.05%, MvP drop x3,
  MvP/miniboss cards 0.01%, item-based x2, quest exp x2.
- No custom items. Gepard 3.0 protects the game client only, not the web CP.

## Data sources (recon CONFIRMED live, 2026-07-05)

All from the server's own FluxCP at `the control panel/` (login-walled; session
cookie shared; Cloudflare present but passive — analytics beacon only).

| Source | URL params | Refresh | What it gives |
|---|---|---|---|
| Vendors | `module=merchant&action=vendors&p=N` | daily | ~12,350 listings, 20/page, ~618 pages |
| Buyers | `module=merchant&action=buyers&p=N` | daily | buying-store orders = **direct demand** (verified: 357 Ygg Seeds wanted @ 22,314z) |
| Monsters | `module=monster&action=view&id=X` | monthly | **server-authoritative drop tables, x5 multipliers already applied** (verified: Anolian → Oridecon 6.7%, Brooch 0.05%) + mob stats (HP etc.) |
| Items | `module=item` | as needed | item metadata |

Row shape (both merchant views): Merchant, Shop, Position (**map + x/y coords**),
Item (**numeric item ID in link — clean integer join key**), Amount, Price
(buyers: Asking Price), Cards; vendor items also carry refine level.

Server-side search exists on vendors: `item_id`, `name`, `type`, `merchant_name`,
`vend_price_op`/`vend_price`, and a `price_order` sort param → cheap targeted
lookups without full pagination.

**RateMyServer is demoted to fallback/cross-check only.** The CP's monster module
supersedes it (authoritative, multipliers baked in, same IDs).

## Architecture

Stack (proven on an earlier project):

```
GitHub Actions (daily cron ~06:00 UTC)
  └─ collector.py — scripted FluxCP login POST (creds in Actions secrets)
       ├─ scrape vendors p=1..N  (N from pagination; throttle ~1 req/s; ~10 min)
       ├─ scrape buyers  p=1..N
       ├─ insert as immutable snapshot (snapshot_id + timestamp; never update in place)
       └─ diff vs previous snapshot → probable_sales
  └─ monthly job: crawl monster module → drop tables + mob stats
       └─ Neon Postgres
            └─ Next.js @ Vercel (same design system as steam-hub/talon)
```

### DB tables (Neon Postgres)

- `snapshots` — id, taken_at, kind (vendors/buyers), complete flag
- `listings` — snapshot_id, merchant, shop, map, x, y, item_id, item_name,
  refine, cards, amount, price
- `buy_orders` — snapshot_id, merchant, map, x, y, item_id, amount, asking_price
- `probable_sales` — diff output: item_id, refine, cards, price, qty, inferred_at
- `monsters` — id, name, level, hp, stats needed for kill-speed
- `drops` — monster_id, item_id, rate (server-true, post-multiplier)
- `items` — id, name, type
- `farm_spots` — curated: map, monster mix, min_level, kills_per_hour_estimate,
  arrow_type, notes
- `farm_sessions` — the player's logged runs: spot, duration, loot counts → calibration
- `quest_turnins` — from wiki: quest form (item/hunt), item_id or monster_id,
  qty required, base/job exp, npc name+location, min/max level, npc_price +
  npc_location if NPC-purchasable, player_vendable flag

### Snapshot diffing (the demand signal)

Listing identity = (merchant, item_id, refine, cards, price). Between consecutive
complete snapshots: vanished listing or reduced amount → `probable_sales` row.
Accumulates into per-item **sell-through velocity** (units/day) and
**realized_price** (median price of disappeared listings — closer to what actually
sells than what is listed).

### Failure handling

- Page parse failure → retry ×2 → log + skip; snapshot flagged incomplete;
  diff step skips incomplete snapshots (no false "sales").
- Login failure → abort loudly (red Actions run). No silent stale data.
- CP layout drift → parser tests against stored HTML fixtures catch it.

## Scoring

### Per-item market value

`low_comparable` (lowest +0/no-card listing), `median_comparable`, `supply_count`;
after diff history builds: `sell_through` (units/day) and `realized_price`.

### Farm-spot EV (Pillar 1)

```
zeny_per_hour(spot) = Σ_drops drop_rate × value(item) × kills_per_hour
                      − consumable_cost_per_hour (arrows, per spot)
value(item) = realized_price if sales data exists, else low_comparable,
              × liquidity_factor (dampens items that never sell)
```

Card drops are included in EV and additionally displayed as
**"expected kills to first card ≈ 1/p"** (e.g. 0.05% → ~2,000 kills), with the
honest caveat that 1/p kills ≈ 63% chance, not certainty.

### Kill-speed model (three tiers, the honest weak link)

1. **v1 seed:** curated `farm_spots` (~15–20 known Sniper spots) with rough
   kills/hr from mob HP (CP data) vs Sniper DPS at 72, mob density, spawn maps.
   Drafted by assistant, sanity-checked by the player.
2. **Calibration:** logged `farm_sessions` override estimates per spot.
3. **Honesty:** every EV displays confidence badge — `estimated` vs `calibrated`.

### Gap scoring (Pillar 2)

- **Buyer-order arbitrage:** asking_price × qty joined to drops →
  "357 Ygg Seeds wanted at 22.3k — farmable at spot X, ~8M available." Sorted by
  total zeny ÷ estimated farm time.
- **Scarcity watch:** high historical value + supply_count ≤ 2 → flagged
  ("you set the price"), tiebroken by sell-through (thin supply ≠ demand).
- **Flip finder:** listings priced far below realized/median price →
  buy-low/re-vend margins. Unlocks after ~1 week of diff history; UI shows
  "collecting sales data, N days left" until then.

### EXP economy (the loop)

- Turn-in data source: **`the server wiki: Repeatable_Quests/`** — complete tables
  for both quest forms, with exact Base/Job EXP values (already include the
  server's quest-exp x2). One-time parse into `quest_turnins`, manual refresh
  if the wiki changes. No hand-curation needed.
- Two quest forms, both modeled:
  - **Item turn-ins** (20/25/50 of an item): joined to live vendor prices →
    **exp-per-zeny ranking** ("cheapest EXP on the market right now"); flags
    cheap-mat dumps. Level brackets matter — e.g. Bacillus expires at 74
    (use-it-now window at 72).
  - **Monster hunting** (50/100/150 kills): joined to `farm_spots` → the Grind
    Board surfaces **combo spots** where a hunt-quest monster also scores on
    zeny/hr — grind zeny while the hunt pays EXP on the same kills (e.g. Ice
    Titan 70–95: 3.64M base per 50 kills).
- **NPC-purchasable turn-in items** (wiki lists them, e.g. Antelope Horn from
  the Niflheim Tool Dealer, 70–85 bracket) = direct unlimited zeny→EXP pipe at
  fixed NPC price, no market dependency. `quest_turnins` carries an
  `npc_price`/`npc_location` column; the EXP Planner ranks NPC pipes alongside
  market buys. (Antelope Horn: no Discount skill, not player-vendable.)
- `farm_spots.min_level` gates the Grind Board: locked spots show what leveling
  buys ("unlocks at 85: +6M/hr") so EXP spend reads as investment with visible ROI.

## Dashboard (Next.js @ Vercel)

Same design system as steam-hub/talon (purple accent, Outfit/Inter). Views:

1. **Grind Board** (home) — ranked spots: zeny/hr, confidence badge, top 3 value
   drops, expected-kills-to-card, arrow cost, map; locked spots greyed with
   unlock level + projected zeny/hr.
2. **Market Gaps** — three panels: Buyer Orders (joined to farm spots, sorted by
   total zeny), Scarcity Watch, Flips (greyed until diff history matures).
3. **EXP Planner** — exp-per-zeny ranking across all three EXP sources (market
   turn-in mats, NPC-pipe items like Antelope Horn, hunt-quest combos);
   "budget X zeny → Y levels" estimator; cheap-mat-dump alerts; expiring-bracket
   warnings (e.g. Bacillus ends at 74).
4. **Item Drill-Down** — price history chart (low/median per snapshot), current
   listings with refine/cards/position coords, sell-through trend, dropping
   monsters + rates.
5. **Session Logger** — mobile-friendly calibration form (spot, duration, loot
   counts); personal zeny/hr track record per spot.

Auth: none or single shared secret (personal tool; decide at deploy).

## Rollout

1. Collector + schema → first scrape runs immediately (history clock starts;
   flip-finder's week-long warmup runs during dashboard build).
2. Snapshot diffing.
3. Scoring queries.
4. **Shortlist script** — Grind Board as terminal/markdown output.
   ← *first "farm this tonight" insight lands here, before any frontend.*
5. Next.js views.
6. Session logger + calibration.
7. EXP Planner (turn-in table parsed once from the wiki page).

## Testing

- Parser unit tests against stored HTML fixture pages (vendors, buyers, monster).
- Scoring unit tests with known drop/price fixtures.
- Diff logic tests against synthetic snapshot pairs (vanish, amount-decrease,
  incomplete-snapshot skip).

## Open items (non-blocking, resolve during implementation)

- Exact FluxCP login POST fields (inspect login form at build time).
- Curated seed data: farm_spots list (~15–20 Sniper spots with kills/hr estimates).
- Antelope Horn NPC price (check in-game at the Niflheim Tool Dealer).
- Whether the monster module has a crawlable index page or needs an ID sweep.
- Neon project + Vercel project + GitHub repo names/creation.
