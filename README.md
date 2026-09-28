# AutoPBI — Dashboards from YAML

[![ci](https://github.com/Pradeepkarra1/auto-pbi/actions/workflows/ci.yml/badge.svg)](https://github.com/Pradeepkarra1/auto-pbi/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Describe your KPIs in YAML. Get a native Power BI dashboard.**

AutoPBI takes clean data + your business rules + the KPI cards stakeholders asked
for, and generates a real **Power BI project (`.pbip`)** — a TMDL semantic model
with DAX measures and a PBIR report with laid-out visuals — that opens directly
in Power BI Desktop. No click-ops, no screen-scraping, no plugins.

```yaml
# dashboard.yaml
project:
  name: Sales Performance
  theme: midnight
data:
  source: data/sales.csv
  date_column: order_date
business_rules:
  - name: Net Revenue
    definition: Gross sales after discounts.
    dax: SUMX(Sales, Sales[quantity] * Sales[unit_price] * (1 - Sales[discount_pct]))
kpis:
  - name: Total Revenue
    rule: Net Revenue
    format: currency
    target: 2800000
    trend: yoy
pages:
  - name: Overview
    visuals:
      - type: kpi_row
      - type: line
        title: Revenue trend
        category: Date.Month
        values: [Total Revenue]
```

```bash
pip install auto-pbi
auto-pbi build --config dashboard.yaml --out ./out
# open out/SalesPerformance.pbip in Power BI Desktop, hit Refresh. Done.
```

---

## Why this exists

Building stakeholder dashboards is 20% analysis, 80% repetition: define the
measures, build the date table, place the cards, format the theme, document what
each KPI means. AutoPBI automates the 80% so analysts spend time on the 20%.

What makes it different:

- **Native output, not screenshots.** It emits the actual Power BI project
  format (TMDL + PBIR) — the same text format Power BI Desktop itself saves.
  The result is a living dashboard you can edit, refresh, and publish, not a
  static export.
- **Business rules become DAX.** Your definitions compile into real measures
  (YoY/MoM/QoQ, targets, variances) — and the **KPI Glossary page** documents
  every rule and its exact DAX inside the dashboard, so stakeholders trust the
  numbers.
- **Zero Power BI automation hacks.** No COM scripting, no UI automation, no
  reverse-engineered binaries. Pure Python, one dependency (`pyyaml`).

## Quickstart

```bash
# 1. Install
pip install auto-pbi            # or: pip install -e . from a clone

# 2. Scaffold a project
auto-pbi init SalesPerformance --dir .
# -> SalesPerformance/dashboard.yaml, SalesPerformance/data/

# 3. Drop your clean CSV into data/ and edit dashboard.yaml

# 4. Validate (no files written)
auto-pbi validate --config SalesPerformance/dashboard.yaml

# 5. Build
auto-pbi build --config SalesPerformance/dashboard.yaml --out ./out
```

Then open `out/SalesPerformance.pbip` in **Power BI Desktop** → **Refresh**.
Desktop loads the model from your data file using the generated Power Query.

> Try it instantly: `examples/sales/` ships with 3,531 rows of sample data and a
> complete `dashboard.yaml`. Run `python scripts/make_sample_data.py`, then build
> it as above.

## How it works

```
dashboard.yaml ─┐
                ├─► plan ─► TMDL semantic model ─┐
clean data ─────┘      (measures, Date table,    ├─► SalesPerformance.pbip
                        relationships)          │
                       └─► PBIR report ──────────┘
                           (pages, visuals, theme,
                            KPI Glossary)
```

1. **Infer** — column types are detected from your CSV/Parquet and drive both
   the TMDL schema and the Power Query `Changed Type` step.
2. **Plan** — business rules and KPIs compile into DAX measures: base
   aggregations, `SAMEPERIODLASTYEAR`/`PREVIOUSMONTH`/`PREVIOUSQUARTER` trends,
   target variance and target-achievement measures. Every name is
   deduplicated — collisions are errors, never silent overwrites.
3. **Model** — writes `*.SemanticModel/definition/`: `database.tmdl`,
   `model.tmdl`, per-table TMDL (fact table with an M partition reading your
   file, a DAX `Date` table, a DAX `KPI Glossary` table), `relationships.tmdl`.
4. **Report** — writes `*.Report/definition/`: `pages.json`, per-page
   `page.json`, per-visual `visual.json` (cards, line/bar/column/area,
   donut/pie, table, matrix, slicer, gauge, textbox), a registered custom
   theme, and a glossary page. An auto-layout engine flows visuals on a
   1280×720 canvas; any visual can pin `x/y/w/h` (overlaps warn at build time).

Full input spec: [`docs/CONFIG_REFERENCE.md`](docs/CONFIG_REFERENCE.md).
Internals: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Test evidence: [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md).

## What a build produces

```
SalesPerformance.pbip
SalesPerformance.SemanticModel/
  definition.pbism
  definition/
    database.tmdl  model.tmdl  relationships.tmdl
    cultures/en-US.tmdl
    tables/Sales.tmdl          # columns + 10 DAX measures + M query
    tables/Date.tmdl           # DAX calendar table (Year/Quarter/Month/...)
    tables/KPI Glossary.tmdl   # DATATABLE documenting every KPI
SalesPerformance.Report/
  definition.pbir
  definition/
    version.json  report.json  pages/pages.json
    pages/overview/page.json
    pages/overview/visuals/<each-visual>/visual.json
    pages/kpi_glossary/...
  StaticResources/RegisteredResources/AutoPBI_Midnight.json
```

## Project layout

```
src/auto_pbi/      # the generator
  cli.py           # init / build / validate
  config.py        # dashboard.yaml loading + validation
  infer.py         # CSV/Parquet schema inference + data-quality warnings
  dax.py           # DAX measure template library
  plan.py          # build plan (single source of truth)
  model.py         # TMDL semantic-model writer
  report.py        # PBIR report writer
  layout.py        # auto-layout engine + overlap detection
  theme.py         # theme presets + custom themes
examples/sales/         # runnable end-to-end example (sales)
examples/supply-chain/  # runnable end-to-end example (OTIF, fill rate, lead time, forecast accuracy)
scripts/           # sample-data generator + use-case test harness
tests/             # pytest suite (unit + use-case integration)
docs/              # config reference, architecture, test report
```

## Roadmap

- [ ] DirectQuery / SQL sources via M parameters
- [ ] Multi-file star schemas (dimension CSVs + auto relationships)
- [ ] Scatter, decomposition-tree visuals
- [ ] Conditional formatting from KPI targets (good/bad semantic colors)
- [ ] `auto-pbi publish` via Fabric REST APIs
- [ ] AI assist: draft `dashboard.yaml` from a data sample + stakeholder notes

## Testing

Two layers, both run in CI:

```bash
.venv/bin/python -m pytest -q              # unit tests + use-case integration
.venv/bin/python scripts/run_usecases.py   # 20 end-to-end scenarios → docs/TEST_REPORT.md
```

The use-case harness builds 20 realistic projects (happy paths: minimal
config, kitchen-sink, special characters, no-date, Parquet, type edges;
negative paths: 10 invalid configs that must fail with clear errors) and
structurally validates every artifact — all JSON parses, every visual
`queryRef` resolves to a real model object, expected measures exist in TMDL.

## Contributing

Issues and PRs welcome. Run the checks locally:

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
python scripts/make_sample_data.py
auto-pbi build --config examples/sales/dashboard.yaml --out /tmp/out
auto-pbi build --config examples/supply-chain/dashboard.yaml --out /tmp/sc_out
```

## License

MIT — see [LICENSE](LICENSE).
