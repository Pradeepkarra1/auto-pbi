# AutoPBI Use-Case Test Report

_Generated 2026-09-28 by `scripts/run_usecases.py` — every result below comes from a real end-to-end build, not from reading the code._

## Summary

- **21 passed**, 0 failed, 0 skipped (21 total)

| Case | Scenario | Result |
| ---- | -------- | ------ |
| UC-01 | Minimal config, everything defaulted | ✅ PASS |
| UC-02 | Kitchen sink: all visuals, trends, targets, rules, theme | ✅ PASS |
| UC-03 | Special characters in names | ✅ PASS |
| UC-04 | No date column | ✅ PASS |
| UC-05 | Parquet source | ✅ PASS |
| UC-06 | Type-inference edge cases | ✅ PASS |
| UC-07 | Custom theme, multi-page, no glossary | ✅ PASS |
| UC-08 | Overlapping explicit layout warns | ✅ PASS |
| UC-09 | Data-quality warnings | ✅ PASS |
| UC-10 | Shipped sales example | ✅ PASS |
| UC-11 | Supply-chain example (OTIF, fill rate, lead time) | ✅ PASS |
| NEG-01 | Unknown KPI reference rejected | ✅ PASS |
| NEG-02 | Trend without date_column rejected | ✅ PASS |
| NEG-03 | Unbalanced DAX rejected | ✅ PASS |
| NEG-04 | Gauge without target rejected | ✅ PASS |
| NEG-05 | Missing data file rejected | ✅ PASS |
| NEG-06 | Duplicate KPI names rejected | ✅ PASS |
| NEG-07 | KPI/rule name clash rejected | ✅ PASS |
| NEG-08 | Duplicate CSV headers rejected | ✅ PASS |
| NEG-09 | Line visual without values rejected | ✅ PASS |
| NEG-10 | Illegal characters in column names rejected | ✅ PASS |

## What each case verifies

### UC-01 — Minimal config, everything defaulted

- all 13 report JSON files parse
- 2 expected measures present in TMDL
- 7 visuals, 12 field refs all resolve to model objects
- no Date table without date_column; pages: Overview, KPI Glossary

### UC-02 — Kitchen sink: all visuals, trends, targets, rules, theme

- all 27 report JSON files parse
- 11 expected measures present in TMDL
- 20 visuals, 32 field refs all resolve to model objects
- area/matrix/gauge visuals present with correct roles
- glossary-only rule (no DAX) documented in KPI Glossary
- Date table + Sales.order_date -> Date.Date relationship present
- custom theme 'Custom Teal' registered with custom palette

### UC-03 — Special characters in names

- all 11 report JSON files parse
- TMDL identifiers quoted: 'Sales Data', 'Net Revenue ($)', 'Revenue (USD)'
- 5 visuals, 6 field refs all resolve to model objects
- Power Query M Changed Type handles special column names
- relationship uses quoted fromColumn

### UC-04 — No date column

- all 12 report JSON files parse
- 6 visuals, 10 field refs all resolve to model objects
- no Date table and empty relationships.tmdl without date_column

### UC-05 — Parquet source

- 6 visuals, 11 field refs all resolve to model objects
- M partition uses Parquet.Document; dtypes mapped (double/int64/boolean/dateTime)

### UC-06 — Type-inference edge cases

- inference: yes/no/true -> boolean; 1/0 -> int64; mixed date formats -> dateTime
- 6 visuals, 11 field refs all resolve to model objects

### UC-07 — Custom theme, multi-page, no glossary

- glossary: false -> no KPI Glossary table/page; pages: One, Two
- 4 visuals, 3 field refs all resolve to model objects

### UC-08 — Overlapping explicit layout warns

- build succeeds; stderr warns about overlapping visuals 'A' with 'B'

### UC-09 — Data-quality warnings

- warnings emitted for all-empty and >50%-empty columns; build still succeeds

### UC-10 — Shipped sales example

- all 18 report JSON files parse
- 10 expected measures present in TMDL
- 12 visuals, 20 field refs all resolve to model objects
- example: 10 measures, pages: Overview, KPI Glossary

### UC-11 — Supply-chain example (OTIF, fill rate, lead time)

- all 27 report JSON files parse
- 15 expected measures present in TMDL
- 20 visuals, 32 field refs all resolve to model objects
- glossary-only 'Perfect Order' rule documented with its definition
- multi-line OTIF DAX (with &&) intact in TMDL
- supply-chain example: 31 measures, pages: Overview, Fulfillment Detail, KPI Glossary

### NEG-01 — Unknown KPI reference rejected

- rejected as expected (mentions 'unknown kpi')

### NEG-02 — Trend without date_column rejected

- rejected as expected (mentions 'date_column')

### NEG-03 — Unbalanced DAX rejected

- rejected as expected (mentions 'unbalanced')

### NEG-04 — Gauge without target rejected

- rejected as expected (mentions 'target')

### NEG-05 — Missing data file rejected

- rejected as expected (mentions 'not found')

### NEG-06 — Duplicate KPI names rejected

- rejected as expected (mentions 'duplicate kpi')

### NEG-07 — KPI/rule name clash rejected

- rejected as expected (mentions 'both kpi and business rule')

### NEG-08 — Duplicate CSV headers rejected

- rejected as expected (mentions 'duplicate column')

### NEG-09 — Line visual without values rejected

- rejected as expected (mentions 'needs at least one entry')

### NEG-10 — Illegal characters in column names rejected

- rejected as expected (mentions 'quote')

## How to re-run

```bash
cd ~/workspace/your_files/auto-pbi
.venv/bin/python scripts/run_usecases.py
```

The script rebuilds every scenario in a temp directory, structurally validates the output (all JSON parses, every visual `queryRef` resolves to a real measure/column in the TMDL model, expected measures exist, page order is correct), then regenerates this file.

## Manual step (needs Power BI Desktop on Windows)

Open any generated `.pbip` in Power BI Desktop and press **Refresh**. Automated checks cover structure and references; only Desktop can verify visual rendering on your installed version.
