# dashboard.yaml — Configuration Reference

`dashboard.yaml` is the single input that describes **what** the dashboard should show.
AutoPBI figures out **how**: it infers the data schema, writes DAX, builds the
TMDL semantic model and lays out the PBIR report.

```yaml
project:
  name: Sales Performance
  description: "Executive sales overview."
  theme: midnight

data:
  source: data/sales.csv
  table: Sales
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

glossary: true
```

---

## `project`

| Key           | Required | Description |
|---------------|----------|-------------|
| `name`        | yes      | Dashboard name. Sanitized to PascalCase for `.pbip` file/folder names (`Sales Performance` → `SalesPerformance`). |
| `description` | no       | Free text, kept for future use (report metadata). |
| `theme`       | no       | Preset name (`midnight`, `corporate`, `forest`, `sunset`) or a custom mapping (see Themes). Default: `midnight`. |

## `data`

| Key           | Required | Description |
|---------------|----------|-------------|
| `source`      | yes      | Clean CSV (or Parquet) file. Relative paths resolve against the YAML location. |
| `table`       | no       | Model table name. Default: source file name without extension. |
| `date_column` | no       | A date/datetime column. Enables the auto `Date` table, the relationship, and YoY/MoM/QoQ trends. |
| `date_table`  | no       | Generate the DAX `Date` table. Default `true` when `date_column` is set. |

Column types are inferred from the file (int → `int64`, float → `double`,
date → `dateTime`, true/false → `boolean`, else `string`) and written into both
the TMDL model and the Power Query `Changed Type` step.

## `business_rules`

Named definitions of how the business measures things. Each rule has a `name`,
a plain-English `definition`, and an optional `dax` expression.

- Rules **with** `dax` become model measures (folder *Business Rules*).
- Rules **without** `dax` are documentation-only — they still appear in the
  auto-generated KPI Glossary page.
- KPIs can build on a rule via `rule: <name>` instead of re-implementing logic.

## `kpis`

Each KPI compiles to one or more DAX measures.

| Key           | Required | Description |
|---------------|----------|-------------|
| `name`        | yes      | Measure name (also the card title). |
| `description` | no       | Shown in the KPI Glossary page. |
| `column`      | *        | Base column on the fact table. |
| `rule`        | *        | Build on a business rule instead of a column. |
| `aggregation` | no       | `sum` (default), `avg`, `min`, `max`, `count`, `distinct_count`. Needs `column`. |
| `dax`         | *        | Raw DAX override. Wins over `column`/`rule`. |
| `format`      | no       | `number` (default), `currency`, `percent`, `decimal`, `integer`. |
| `target`      | no       | Numeric target. Creates `<name> Target`, `<name> vs Target` and `<name> Target %` (achievement) measures. |
| `trend`       | no       | `none` (default), `yoy`, `mom`, `qoq`. Creates `<name> YoY %` etc. Needs `data.date_column`. |
| `show_card`   | no       | Include in `kpi_row` visuals. Default `true`. |

\* one of `dax`, `column` (+`aggregation`), or `rule` is required.

## `pages`

A list of report pages. If omitted, AutoPBI generates a sensible `Overview` page
(KPI cards → trend chart → detail table) automatically.

### Visual types

| Type      | Power BI visual | Binds |
|-----------|-----------------|-------|
| `kpi_row` | N × Card (new)  | `kpis: [...]` or all `show_card` KPIs |
| `kpi`     | Card (new)      | `value: <KPI>` |
| `line`    | Line chart      | `category`, `values: [...]`, `series:` (optional) |
| `bar`     | Bar chart       | `category`, `values: [...]`, `series:` (optional) |
| `column`  | Column chart    | `category`, `values: [...]`, `series:` (optional) |
| `area`    | Area chart      | `category`, `values: [...]`, `series:` (optional) |
| `donut`   | Donut chart     | `category`, `values: [<one>]` |
| `pie`     | Pie chart       | `category`, `values: [<one>]` |
| `table`   | Table           | `columns: [...]` |
| `matrix`  | Matrix          | `rows: [...]`, `category:` (column groups), `values: [...]` |
| `slicer`  | Slicer          | `field:` |
| `gauge`   | Gauge           | `value: <KPI>`, target from KPI `target:` or visual `target:` number |
| `textbox` | Text box        | `text:` |

### Field references

- `Table.Column` for columns (`Sales.region`), `Date.Month` / `Date.Year` for the date table.
- A bare `Column` resolves against the fact table.
- A KPI name (e.g. `Total Revenue`) binds the generated measure.

### Layout

Pages auto-flow on a 1280×720 canvas (KPI cards → charts → tables). Any visual
accepts explicit `x`, `y`, `w`, `h` to pin its position.

```yaml
- type: bar
  title: Revenue by region
  category: Sales.region
  values: [Total Revenue]
  x: 16
  y: 240
  w: 620
  h: 330
```

## `glossary`

Default `true`. Appends a **KPI Glossary** page: a table listing every business
rule and KPI, its definition, and the exact DAX AutoPBI generated. This is the
stakeholder-trust feature — the dashboard documents its own logic.

## Themes

Built-in presets: `midnight`, `corporate`, `forest`, `sunset`. Or go custom:

```yaml
project:
  theme:
    name: Acme Theme
    preset: corporate        # start from a preset...
    background: "#FFFFFF"
    foreground: "#1A1A1A"
    palette: ["#0F4C81", "#E46A2E", "#6A9F46", "#C9A227",
              "#7D5BA6", "#35A7FF", "#E55934", "#9BC53D"]
    # `palette:` also accepts the aliases `dataColors:` and `colors:`.
```

Overlapping explicit `x`/`y`/`w`/`h` positions produce a build-time warning
(pointing at the two visuals) instead of silently stacking them.

## Validation

`auto-pbi validate --config dashboard.yaml` checks the YAML, the data file,
column/type references, DAX bracket balance and cross-references — without
writing anything. `auto-pbi build` runs the same checks, then writes the project.

Rejected up front with a clear message: duplicate KPI/rule/page names, a KPI
and rule sharing a name, duplicate (case-insensitive) CSV headers, empty or
illegal column names, unknown KPI/column references, trends without
`data.date_column`, gauges without any target, and visuals missing required
bindings (e.g. a `line` with no `values:`). Non-fatal data-quality observations
(all-empty columns, >50% blank columns) print as warnings.
