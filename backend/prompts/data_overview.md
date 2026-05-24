# Data Overview

Dataset: ~4,574 tariff lines across ~1,200 distinct customs entries,
Oct 2024 – Mar 2025, all ocean mode.

## Customers (`customer_code`)

- `MHF` — Meridian Home Furnishings (furniture, textiles, lighting)
- `PCA` — Pacific Coast Apparel (apparel, accessories)
- `SAG` — Summit Athletic Gear (footwear, sports equipment)

## Countries of origin (`country_of_origin_code`)

`CN` (China), `VN` (Vietnam), `IN` (India), `ID` (Indonesia),
`BD` (Bangladesh), `TW` (Taiwan), `KR` (South Korea).

## Ports of entry (`port_of_entry_code` → name)

`1001` New York/Newark · `1701` Charleston · `2704` Los Angeles ·
`2809` Long Beach · `5301` Houston.

## Period filters (pre-computed string columns)

- `release_year_month` — `"YYYY-MM"` (e.g., `"2025-01"`).
- `release_year_quarter` — `"YYYY-Qn"` (e.g., `"2025-Q1"`).

Always filter periods via these string columns. They are pre-computed on
both views; do not parse dates client-side.

## Grain selection

- **`entries_v`** — one row per customs entry. Use for entry counts,
  entry-grain financial totals (it carries `total_mpf_capped` and
  `total_duty_taxes_fees_correct` with the per-entry MPF cap applied).
- **`entry_lines_v`** — one row per tariff line. Use for line-grain
  queries (HTS code, units, line-level duty contributions). Country of
  origin is a line-level attribute — when filtering by
  `country_of_origin_code`, use `entry_lines_v`.
