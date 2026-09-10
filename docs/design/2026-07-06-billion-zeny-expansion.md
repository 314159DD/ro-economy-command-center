# Billion-Zeny Expansion - Design Spec (2026-07-06)

Seven features that turn the command center from a market viewer into a money
engine. Goal: repeatable daily income plus structural plays, measured, toward
1B zeny. Approved scope from brainstorm; this spec fixes the integration design.

## Shared plumbing (build first)

**S1. Item stats module.** One function produces, per item, the numbers every
new feature needs: `item_stats(listings, sales, buy_orders, npc_sell)` ->
`{item_id: {low, median, supply, sellers, realized_med, velocity_day, n_sales,
best_bid, npc_sell}}`. Mostly re-exposes market_stats + sales aggregation.
Velocity = qty sold / window days (probable_sales, 7d window). Confidence
tiers: n_sales >= 3 "proven", 1-2 "thin", 0 "unproven".

**S2. Dashboard settings.** A small settings object in localStorage
(`ro_settings_v1`): capital budget (zeny the user is willing to deploy),
watchlist (item ids). A gear popover in the header edits capital; stars on
item rows edit the watchlist. All client-side; JS-computed views (digest,
corners) read it live.

## The seven features

### F1. Market Maker (new tab)
The compounder: buy below realized value, vend at realized value, repeat.
- Row per item where: n_sales >= 3, velocity_day >= 1, spread% >= 10%
  (spread = realized_med - low).
- Columns: item, buy at (low), cheap qty (units listed below realized_med),
  realized med, velocity/day, spread/ea, est profit/day
  (= min(velocity_day, cheap_qty) x spread), capital needed, days to turn
  (cheap_qty / velocity_day), where (cheapest vendor).
- Sort default: est profit/day desc. Secondary metric shown: ROI/day
  (profit_day / capital).
- Vending tax: the server charges a vending tax (check wiki; assume 2% until
  verified, constant `VENDING_TAX`). Applied to spread.
- Gets better automatically as sales history accrues; works from day 3+.

### F2. Corners (new tab)
Scarcity plays: buy ALL supply of a proven-demand item, relist higher.
- Row per item where: total comparable supply cost <= capital budget (from
  settings; default 10M), sellers <= 8, and demand proof
  (velocity_day >= 2 OR total buy-order demand >= cost).
- Columns: item, sellers, total qty, cost to corner, current low, realized
  med, velocity/day, days of monopoly (qty / velocity), suggested relist
  (realized_med x 1.5, capped at 3x low), est payoff over one monopoly
  window (= qty x (relist x (1-tax) - avg cost)), where (all vendor maps,
  comma list).
- Rows honestly labeled with confidence tier; unproven demand excluded.
- Explicit note in tab: check server rules on market cornering; user's call.

### F3. Farm-to-order (Buyer Orders tab upgrade)
Cross every standing buy order with the damage model.
- For each buy-order row that has a farmable drop source: model kph for the
  source mob (existing model_kills_per_hour), z/hr farming for this order
  (= rate/100 x bid x kph), hours to fill (= qty_wanted / (rate/100 x kph)).
- New columns: Farm z/hr, Hours to fill; default sort switches to Farm z/hr.
- Mob sprite + kills/min override (same kpm-edit mechanism, shared keys).
- Rows without a drop source keep '-' and sort last.

### F4. Spot discovery (Grind Board addition)
Rank ALL mobs, not just the 16 curated spots.
- Second collapsible table "Discovered spots" under the curated board: one
  row per monster with boss_class normal, spawn density >= 15, level <= 99+20.
- Reliable z/hr = sum over non-lottery drops (rate x value) x model kph
  x density_factor, where density_factor = min(1, density / 40) keeps
  sparse maps honest. Arrow cost ignored (unknown per mob; noted).
- Columns: mob (sprite), densest map (xN), lvl, hp, model kph (kpm-editable,
  shared keys), reliable z/hr, exp/hr, top 3 drops.
- Curated spots excluded from the discovered list (no duplicates).

### F5. Merchants (new tab)
Profile sellers across snapshot history; find the habitually-cheap ones.
- Per merchant name, across ALL vendor snapshots: listings seen, distinct
  items, hit rate (fraction of listings priced below the item's realized_med
  at any time), avg discount% on those hits, total undercut value, last seen
  (date + map/coords of latest shop).
- Row filter: >= 5 listings seen and >= 2 hits. Sort: total undercut value.
- Needs a new Store query over listings x snapshots (history already stored;
  no schema change). Grows more useful every day.

### F6. War Chest (new tab, phased)
WoE-cycle plays on consumables.
- Static data: WoE schedule from the the server wiki/CP ("WOE Hours" page) as a
  seed file (`seeds/woe_schedule.csv`); countdown to next WoE in the tab.
- Curated war-supplies item list (`seeds/war_supplies.csv`: pots, converters,
  gems, ammo, foods; ids + names). Tab shows each with current low, realized
  med, velocity, 7d price sparkline (reuse chart), and days-until-WoE.
- Phase 2 (auto-activates with >= 3 weeks history): day-of-week price/velocity
  pattern per item and buy/sell window suggestions. Until then the panel says
  "collecting cycle data - week X".

### F7. Ledger, digest, 1B progress (hero + new CLI)
Measurement and execution layer.
- `log_trade.bat` / `python -m ro_collector.log_trade`: record buys/sells
  (`--buy/--sell <item_id|name> --qty N --price P --strategy flip|snipe|
  corner|mm|grind|other`). New `trades` table.
- `log_balance.bat`: record current total zeny (`balances` table). The hero
  gains a 1B progress bar from the latest balance + sparkline of balances.
- Strategy P&L: realized profit per strategy from paired buys/sells (FIFO
  within item+strategy), shown in a small "P&L" card on the hero row or a
  section on the Market Maker tab.
- Action digest: client-side JS panel above the tabs: top 3 flips, top 3
  snipes, market-maker restocks (watchlist items whose cheap supply
  replenished), corner candidates within capital, all filtered by settings.
  Collapsible; hidden when empty.

## Data / schema changes

- `trades` table: id, ts, item_id, item_name, side buy|sell, qty, price,
  strategy, note.
- `balances` table: id, ts, zeny.
- No changes to snapshots/listings; F5 reads existing history.
- Seeds: `woe_schedule.csv`, `war_supplies.csv`.

## Tab layout after

Grind Board (+discoveries) | Lotteries | Flipping | Snipes | Market Maker |
Corners | Item Explorer | Buyer Orders (farm-to-order) | Merchants |
War Chest | EXP Planner. The digest panel sits between hero and tabs.
(EXP Planner stays; zero maintenance.)

## Build order

1. S1 item stats + S2 settings plumbing
2. F3 farm-to-order (small, pure reuse; revives Buyer Orders)
3. F4 spot discovery
4. F1 Market Maker
5. F2 Corners
6. F5 Merchants
7. F7 ledger + digest + 1B bar
8. F6 War Chest v1 (schedule + watch items; cycle analytics later)

Each step: TDD (pytest), rebuild, node JS-parse check, browser spot-check,
commit. Kills/min override keys, icons, tooltips, day/night theming and the
no-em-dash rule apply everywhere.

## Verification

Full suite green after each feature; final browser pass across all tabs in
both modes; real-data sanity numbers quoted in each commit message.
