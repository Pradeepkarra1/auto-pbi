# AutoPBI Architecture

How a `dashboard.yaml` becomes a native Power BI project. This document is
for contributors and for anyone who wants to understand (or trust) what the
generator writes into their `.pbip`.

## Pipeline

```
dashboard.yaml ─┐
                ├─► load_config()   YAML → typed dataclasses + full validation
clean data ─────┘
                        │
                        ▼
                infer_schema()    sample the data → ColumnInfo list
                        │         (tmdl_type + M type + date_only per column)
                        ▼
                build_plan()      the single contract: measures, glossary rows,
                        │         relationships, date-table decision
               ┌────────┴────────┐
               ▼                 ▼
   write_semantic_model()   write_report()
   TMDL text files          PBIR JSON files
               └────────┬────────┘
                        ▼
              <Project>.pbip  (points at the .Report and .SemanticModel)
```

Every decision is made **once, up front, in `build_plan()`**. The TMDL writer
and the PBIR writer never derive anything independently — they both render
the same plan, so a visual can never reference a measure that doesn't exist.
The use-case harness (`scripts/run_usecases.py`) verifies exactly that:
every `queryRef` in every visual must resolve to a real measure or column in
the generated model.

## Stage 1 — Config (`config.py`)

`load_config()` parses the YAML into typed dataclasses and then validates
aggressively, because a bad config caught here is a clear CLI error instead
of a broken report in Desktop:

- unknown enum values (aggregation, trend, format, visual type),
- duplicate KPI / rule / page names, and KPI↔rule name clashes (each becomes
  a DAX measure, so collisions would silently overwrite),
- dangling references (KPI → rule, visual → KPI),
- KPIs that set both `column` and `rule`, or neither,
- trends without `data.date_column`,
- gauges without any target (neither KPI `target:` nor visual `target:`),
- visuals missing required bindings (a `line` with no `values:`, a `matrix`
  with neither `rows:` nor `values:`).

## Stage 2 — Schema inference (`infer.py`)

The first 2,000 data rows are sampled per column and classified in priority
order: string → date → boolean → float → int. Details that matter:

- **Booleans** are word-only (`yes/no/true/false/y/n`). Bare `1`/`0` stay
  integers — far more useful for a `count`/`sum`.
- **Dates** accept the common formats (`%Y-%m-%d`, `%m/%d/%Y`, …) with and
  without times; a column is `type date` only when every value is
  midnight, otherwise `type datetime`.
- **Duplicate headers** (case-insensitive) are rejected — `csv.DictReader`
  would otherwise silently collapse them and drop a column.
- **Data-quality warnings** (not errors): all-empty columns and >50%-blank
  columns are reported on stderr during `validate` and `build`.

## Stage 3 — Planning (`plan.py`)

`build_plan()` turns config + schema into a `BuildPlan`:

- **Fact table name**: `data.table`, else the file stem. Path separators and
  quote/control characters in column names are rejected here.
- **Measures**: rules with DAX → *Business Rules* folder; each KPI → its base
  measure; `trend:` adds `<name> YoY %` / `MoM %` / `QoQ %` (*Time
  Intelligence*); `target:` adds `<name> Target`, `<name> vs Target` and
  `<name> Target %` (*Targets*); numeric gauge targets add `<title> Target`.
  Every measure name is deduplicated — a collision is a `ConfigError`, never
  a silent overwrite.
- **Date table**: when `data.date_column` is set, a DAX calculated `Date`
  table is generated spanning `MIN`/`MAX` of the fact date column, with
  Year / Quarter / Month / Month Key / Month Number / Year-Month Number /
  Day, and `Month` sorted by `Month Key` so charts order chronologically.
  The relationship `<table>.<date_column> → Date.Date` is recorded.
- **Glossary rows**: every rule and KPI with its definition and generated
  DAX — the source for the KPI Glossary page.

## Stage 4a — Semantic model (`model.py`, TMDL)

Writes `<Project>.SemanticModel/definition/`:

| File | Contents |
| ---- | -------- |
| `database.tmdl`, `model.tmdl`, `cultures/en-US.tmdl` | database/model shell (compatibility level 1567) |
| `tables/<Table>.tmdl` | columns (type, format, `summarizeBy: none`), all measures, the M import partition |
| `tables/Date.tmdl` | calculated Date table (optional) |
| `tables/KPI Glossary.tmdl` | `DATATABLE` of KPI/definition/DAX (optional) |
| `relationships.tmdl` | fact → Date relationship |

Conventions: tab indentation, UTF-8 without BOM, LF endings,
single-quoted identifiers when a name contains spaces or punctuation
(`table 'Sales Data'`, `measure 'Revenue (USD)' =`). The Power Query M
partition reads the source file on refresh (`Csv.Document` /
`Parquet.Document`) and applies the inferred `Changed Type` step; column
names are M-escaped (embedded `"` doubled).

## Stage 4b — Report (`report.py`, PBIR)

Writes `<Project>.Report/definition/`:

| File | Contents |
| ---- | -------- |
| `definition.pbir` | version + dataset reference (by path to the `.SemanticModel`) |
| `definition/version.json`, `report.json` | PBIR version, theme binding, report settings |
| `definition/pages/pages.json` | page order + active page |
| `definition/pages/<slug>/page.json` | 1280×720 canvas, `FitToPage` |
| `definition/pages/<slug>/visuals/<v>/visual.json` | one `visualContainer` per visual |
| `StaticResources/RegisteredResources/<Theme>.json` | generated theme |

Each visual binds model fields through
`visual.query.queryState.<Role>.projections` with
`queryRef: "<Table>.<Field>"` — measures as `{"Measure": …}`, columns as
`{"Column": …}`. Visual-type mapping:

| Config `type` | PBIR `visualType` | Roles |
| --- | --- | --- |
| `kpi` | `cardVisual` | Data |
| `kpi_row` | N × `cardVisual` | (expanded before layout) |
| `line` | `lineChart` | Category, Series?, Y |
| `bar` / `column` / `area` | `clusteredBarChart` / `clusteredColumnChart` / `areaChart` | Category, Series?, Y |
| `donut` / `pie` | `donutChart` / `pieChart` | Category, Y |
| `table` | `tableEx` | Values |
| `matrix` | `pivotTable` | Rows, Columns, Values |
| `slicer` | `slicer` | Values |
| `gauge` | `gauge` | Y, TargetValue |
| `textbox` | `textbox` | — |

Sensible defaults are applied: line/area charts sort ascending by category,
bar/column sort descending by the first measure, gauge titles default to the
KPI name.

### Layout (`layout.py`)

A 12-column flow grid on a 1280×720 canvas with 16pt margins: KPI cards on
top, charts in the middle, tables at the bottom. Any visual can pin explicit
`x`/`y`/`w`/`h`. After layout, explicit positions are checked for overlap —
an overlap prints a warning naming both visuals instead of silently stacking
them.

### Themes (`theme.py`)

Presets (`midnight`, `corporate`, `forest`, `sunset`) or a custom mapping
(`name`, `preset`, `background`, `foreground`, `palette` — with `dataColors`
and `colors` accepted as aliases). The theme is written as a registered
resource and bound in `report.json`.

## Testing

- **Unit tests** (`tests/`, pytest): DAX templates, TMDL quoting, inference,
  layout math, config validation — fast and hermetic.
- **Use-case harness** (`scripts/run_usecases.py`): 20 end-to-end scenarios
  (10 happy paths incl. special characters, parquet, no-date, type edges;
  10 negative paths that must fail with clear errors). Each successful build
  is structurally validated — all JSON parses, every visual `queryRef`
  resolves, expected measures exist in TMDL, page order is correct — and the
  harness regenerates `docs/TEST_REPORT.md` from the real results.
- **Manual**: open the `.pbip` in Power BI Desktop and press Refresh. Only
  Desktop can verify rendering on a given version.

## Design principles

1. **Config is the single source of truth** — no hidden defaults that change
   the data.
2. **Fail fast with a clear message** — every invalid input is a `ConfigError`
   naming the exact key, not a broken artifact.
3. **Plan once, render twice** — model and report can never disagree.
4. **The dashboard documents itself** — the KPI Glossary page ships the
   definition and DAX of every rule and KPI.
