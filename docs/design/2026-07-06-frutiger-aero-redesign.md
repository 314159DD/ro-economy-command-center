# Frutiger Aero Redesign — Design Spec (2026-07-06)

Approved via visual mockups.

## Goal

Full visual overhaul of the generated dashboard (`report.py` `_TEMPLATE`). Two Frutiger
Aero themes with a day/night toggle, a new hero section, and "going all out" on motion —
without touching the data pipeline or any behavior the 97 tests pin down.

## Themes (CSS-variable driven, `body[data-mode]`)

- **Day — "Classic Sky"**: cyan→white sky gradient, white glossy panels (top-edge shine),
  grass-green accent strip footer, floating glass bubbles, blue glossy pill tabs.
- **Night — "Dawn Aero"**: indigo→sunset sky, warm frosted glass panels (backdrop-blur),
  amber/peach accents, aurora strip footer, same bubbles dimmed.
- Toggle: sun/moon glossy orb in the header. Default by local hour (07:00–18:59 day,
  else night); manual choice persisted in `localStorage["ro_mode"]` and wins.
- Mode switch animates (CSS transition on colors/背景, ~0.4s).
- The RO item tooltip stays dark-navy in both modes (it is deliberately an in-game artifact).

## Hero section (below header, above tabs)

Derived entirely in JS from DATA (no Python changes):

- **"Farm tonight" featured card** (~1.5x width): #1 open grind spot after kills/min
  overrides — mob sprite, spot name, reliable z/hr, map+density, best arrow, exp/hr.
- **Three stat tiles**: Best flip (`flips[0]`: total profit + item), Top snipe
  (`undercuts[0]`: potential + item), Buyer demand (Σ `buyer_orders.demand_total` + item count).
- Hero numbers **count up** on load (~800ms); hero refreshes when kills/min overrides change.
- Clicking a hero card switches to its tab.

## Motion

- Staggered load-in: header → hero cards → tabs → active panel (fade + translateY, 60–90ms steps).
- Tab switch: panel fade/slide-in (~200ms).
- Hover: shine sweep on tiles/tabs/pills; row hover glow.
- Background bubbles drift slowly (GPU transform keyframes only).
- `prefers-reduced-motion: reduce` disables all of the above.
- Performance guard: no per-row animations on the big tables; backdrop-blur limited to
  hero/panels, not table rows.

## Charts

Series colors re-validated per surface with the dataviz validator (they were only
validated for the old dark surface): pick a passing purple/green pair for the day surface
and for the night glass surface; `drawChart` reads colors per current mode. Re-run
validator for both.

## Invariants (must not break)

- All DATA keys and row fields; TAB_LABELS; every id/class the tests pin
  (`kpm-edit`, `ro_kpm_v1`, `tt-id`, `chart-tip`, `item-detail`, `uc-body`, `lot-search`,
  `lot-kind-filter`, `card-farmable-toggle`, `item-tooltip`, `mob-ic`, `item-cell`).
- Single self-contained offline file; no external assets.
- Sorting, filters, kills/min editing, detail panels, tooltips all function identically.

## New test hooks

- `id="mode-toggle"` + `ro_mode` present in the page.
- `id="hero"` section present.

## Verification

Full pytest suite; node JS-parse check; browser pass in both modes via local server:
toggle, tab switch, hero numbers, kills/min edit, detail panel, tooltip, hover states,
and screenshots reviewed for layout collisions.
