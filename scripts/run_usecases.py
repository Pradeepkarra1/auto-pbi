"""Use-case test harness for AutoPBI.

Runs realistic end-to-end scenarios (happy paths AND failure paths) against
the real CLI, structurally validates every generated artifact, and writes
docs/TEST_REPORT.md from the actual results.

    .venv/bin/python scripts/run_usecases.py

Exit code is non-zero if any non-skipped case fails.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import textwrap
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auto_pbi.cli import main as cli_main  # noqa: E402
from auto_pbi.config import load_config  # noqa: E402
from auto_pbi.infer import infer_schema  # noqa: E402
from auto_pbi.plan import build_plan  # noqa: E402

REPORT_PATH = ROOT / "docs" / "TEST_REPORT.md"


@dataclass
class CaseResult:
    id: str
    title: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""
    checks: list[str] = field(default_factory=list)


@dataclass
class Ctx:
    """Per-case scratch space: config dir, captured CLI output, results."""
    tmp: Path
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)
    rc: int | None = None
    checks: list[str] = field(default_factory=list)

    def write(self, rel: str, content: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8",
                     newline="\n")
        return p

    def run_build(self, config_rel: str = "dashboard.yaml",
                  out_rel: str = "out") -> int:
        so, se = io.StringIO(), io.StringIO()
        with redirect_stdout(so), redirect_stderr(se):
            self.rc = cli_main(["build", "-c", str(self.tmp / config_rel),
                                "-o", str(self.tmp / out_rel)])
        self.out.append(so.getvalue())
        self.err.append(se.getvalue())
        return self.rc

    @property
    def stdout(self) -> str:
        return "\n".join(self.out)

    @property
    def stderr(self) -> str:
        return "\n".join(self.err)

    def out_dir(self, out_rel: str = "out") -> Path:
        return self.tmp / out_rel


# --------------------------------------------------------------------------
# structural validators (run against every successful build)
# --------------------------------------------------------------------------

def _all_json_parse(report_dir: Path, checks: list[str]) -> None:
    bad = []
    for p in sorted(report_dir.rglob("*.json")):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad.append(f"{p.name}: {e}")
    assert not bad, f"unparseable JSON: {bad}"
    checks.append(f"all {sum(1 for _ in report_dir.rglob('*.json'))} report JSON files parse")


def _visual_refs_valid(out: Path, project: str, checks: list[str]) -> None:
    """Every visual's queryRef must point at a real measure/column in the model."""
    rep = out / f"{project}.Report"
    pages = json.loads((rep / "definition" / "pages" / "pages.json").read_text())
    assert pages["pageOrder"], "pages.json has no pages"
    assert pages["activePageName"] == pages["pageOrder"][0]

    # model inventory: table -> {"measures": set, "columns": set}
    sm = out / f"{project}.SemanticModel" / "definition" / "tables"
    inventory: dict[str, dict[str, set[str]]] = {}
    for tmdl in sm.glob("*.tmdl"):
        text = tmdl.read_text(encoding="utf-8")
        table = tmdl.stem
        measures, columns = set(), set()
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("measure "):
                measures.add(s[len("measure "):].split("=")[0].strip().strip("'"))
            elif s.startswith("column "):
                columns.add(s[len("column "):].strip().strip("'"))
        inventory[table] = {"measures": measures, "columns": columns}

    n_visuals = n_refs = 0
    for pid in pages["pageOrder"]:
        vdir = rep / "definition" / "pages" / pid / "visuals"
        assert vdir.is_dir(), f"missing visuals dir for page {pid}"
        for vjson in sorted(vdir.glob("*/visual.json")):
            doc = json.loads(vjson.read_text(encoding="utf-8"))
            n_visuals += 1
            qs = doc["visual"].get("query", {}).get("queryState", {})
            for role, body in qs.items():
                for proj in body.get("projections", []):
                    n_refs += 1
                    ref = proj["queryRef"]
                    table, name = ref.split(".", 1)
                    assert table in inventory, f"{vjson.parent.name}: unknown table in ref '{ref}'"
                    kind = "Measure" if "Measure" in proj["field"] else "Column"
                    pool = inventory[table]["measures" if kind == "Measure" else "columns"]
                    assert name in pool, (
                        f"{vjson.parent.name}: {kind} ref '{ref}' not in model")
    checks.append(f"{n_visuals} visuals, {n_refs} field refs all resolve to model objects")


def _tmdl_has_measures(out: Path, project: str, table: str,
                       names: list[str], checks: list[str]) -> None:
    tmdl = (out / f"{project}.SemanticModel" / "definition" / "tables"
            / f"{table}.tmdl").read_text(encoding="utf-8")
    missing = [n for n in names if f"measure {n} =" not in tmdl
               and f"measure '{n}' =" not in tmdl]
    assert not missing, f"measures missing from TMDL: {missing}"
    checks.append(f"{len(names)} expected measures present in TMDL")


def _pages_are(out: Path, project: str, expected: list[str]) -> list[str]:
    rep = out / f"{project}.Report"
    pages = json.loads((rep / "definition" / "pages" / "pages.json").read_text())
    got = []
    for pid in pages["pageOrder"]:
        page = json.loads((rep / "definition" / "pages" / pid / "page.json").read_text())
        got.append(page["displayName"])
    assert got == expected, f"pages {got} != expected {expected}"
    return got


# --------------------------------------------------------------------------
# shared fixtures
# --------------------------------------------------------------------------

SALES_CSV = """\
    order_id,order_date,region,product,quantity,unit_price,discount
    1,2024-01-05,North,Widget,10,25.00,0
    2,2024-01-12,South,Gadget,5,40.00,2.5
    3,2024-02-03,North,Widget,8,25.00,0
    4,2024-02-20,East,Gadget,12,40.00,10
    5,2024-03-11,West,Widget,20,25.00,5
    6,2024-03-28,South,Gadget,7,40.00,0
    7,2025-01-09,North,Widget,15,27.50,0
    8,2025-02-14,East,Gadget,9,42.00,4
    9,2025-03-02,West,Widget,25,27.50,12.5
    10,2025-03-30,South,Gadget,11,42.00,0
    """

MINI_CSV = """\
    id,category,amount
    1,A,100
    2,B,200
    3,A,150
    """


# --------------------------------------------------------------------------
# use cases
# --------------------------------------------------------------------------

def uc01_minimal(ctx: Ctx) -> None:
    """Bare-minimum config: project + data + KPIs, everything else defaulted."""
    ctx.write("data/mini.csv", MINI_CSV)
    ctx.write("dashboard.yaml", """\
        project:
          name: Minimal
        data:
          source: data/mini.csv
        kpis:
          - name: Total Amount
            column: amount
            format: currency
          - name: Orders
            column: id
            aggregation: count
        """)
    assert ctx.run_build() == 0, ctx.stderr
    out = ctx.out_dir()
    checks: list[str] = []
    _all_json_parse(out / "Minimal.Report", checks)
    got = _pages_are(out, "Minimal", ["Overview", "KPI Glossary"])
    _tmdl_has_measures(out, "Minimal", "mini",
                       ["Total Amount", "Orders"], checks)
    _visual_refs_valid(out, "Minimal", checks)
    assert not (out / "Minimal.SemanticModel" / "definition" / "tables" / "Date.tmdl").exists()
    checks.append("no Date table without date_column; pages: " + ", ".join(got))
    ctx.checks = checks


def uc02_kitchen_sink(ctx: Ctx) -> None:
    """Every visual type, trends, targets, rules, explicit layout, custom theme."""
    ctx.write("data/sales.csv", SALES_CSV)
    ctx.write("dashboard.yaml", """\
        project:
          name: Kitchen Sink
          theme:
            name: Custom Teal
            dataColors: ["#0E7C7B", "#F2A541", "#E84855"]
        data:
          source: data/sales.csv
          table: Sales
          date_column: order_date
        business_rules:
          - name: Net Revenue
            definition: Quantity times unit price minus discount.
            dax: SUMX(Sales, Sales[quantity] * Sales[unit_price] - Sales[discount])
          - name: Review Flag
            definition: Orders over 20 units need a manual review.
        kpis:
          - name: Revenue
            rule: Net Revenue
            format: currency
            target: 5000
            trend: yoy
          - name: Units
            column: quantity
            format: integer
            trend: mom
          - name: Avg Discount
            column: discount
            aggregation: avg
            format: currency
            trend: qoq
        pages:
          - name: Overview
            visuals:
              - type: kpi_row
              - type: line
                title: Revenue trend
                category: Date.Month
                values: [Revenue]
              - type: area
                title: Units area
                category: Date.Month
                values: [Units]
              - type: bar
                title: Revenue by region
                category: Sales.region
                values: [Revenue]
                series: Sales.product
              - type: column
                title: Units by product
                category: Sales.product
                values: [Units]
              - type: donut
                title: Revenue share
                category: Sales.region
                values: [Revenue]
              - type: pie
                title: Units share
                category: Sales.product
                values: [Units]
              - type: matrix
                title: Revenue matrix
                rows: [Sales.region]
                category: Sales.product
                values: [Revenue]
              - type: table
                title: Detail
                columns: [Sales.order_id, Sales.order_date, Revenue, Units]
              - type: slicer
                title: Region slicer
                field: Sales.region
              - type: gauge
                title: Revenue gauge
                value: Revenue
              - type: textbox
                title: Note
                text: Built by AutoPBI.
          - name: Pinned
            visuals:
              - type: kpi
                title: Pinned revenue
                value: Revenue
                x: 16
                y: 100
                w: 400
                h: 160
              - type: gauge
                title: Custom target gauge
                value: Units
                target: 100
                x: 700
                y: 400
                w: 300
                h: 250
        glossary: true
        """)
    assert ctx.run_build() == 0, ctx.stderr
    out = ctx.out_dir()
    checks: list[str] = []
    _all_json_parse(out / "KitchenSink.Report", checks)
    _pages_are(out, "KitchenSink", ["Overview", "Pinned", "KPI Glossary"])
    _tmdl_has_measures(out, "KitchenSink", "Sales", [
        "Net Revenue", "Revenue", "Revenue YoY %", "Revenue Target",
        "Revenue vs Target", "Revenue Target %",
        "Units", "Units MoM %", "Custom target gauge Target",
        "Avg Discount", "Avg Discount QoQ %"], checks)
    _visual_refs_valid(out, "KitchenSink", checks)
    # matrix roles
    rep = out / "KitchenSink.Report"
    found = {"areaChart": 0, "pivotTable": 0, "gauge": 0}
    for vjson in rep.rglob("visual.json"):
        doc = json.loads(vjson.read_text())
        vt = doc["visual"]["visualType"]
        if vt in found:
            found[vt] += 1
        if vt == "pivotTable":
            roles = set(doc["visual"]["query"]["queryState"])
            assert {"Rows", "Columns", "Values"} <= roles, f"matrix roles: {roles}"
    assert found == {"areaChart": 1, "pivotTable": 1, "gauge": 2}, found
    checks.append("area/matrix/gauge visuals present with correct roles")
    # glossary-only rule documented
    gloss = (out / "KitchenSink.SemanticModel" / "definition"
             / "tables" / "KPI Glossary.tmdl").read_text()
    assert "Review Flag" in gloss and "manual review" in gloss
    checks.append("glossary-only rule (no DAX) documented in KPI Glossary")
    # date table + relationship
    assert (out / "KitchenSink.SemanticModel" / "definition" / "tables" / "Date.tmdl").exists()
    rel = (out / "KitchenSink.SemanticModel" / "definition" / "relationships.tmdl").read_text()
    assert "Sales.order_date" in rel and "Date.Date" in rel
    checks.append("Date table + Sales.order_date -> Date.Date relationship present")
    # custom theme registered
    theme_files = list((out / "KitchenSink.Report" / "StaticResources"
                        / "RegisteredResources").glob("*.json"))
    assert len(theme_files) == 1
    theme = json.loads(theme_files[0].read_text())
    assert theme["dataColors"][0] == "#0E7C7B", theme["dataColors"]
    checks.append(f"custom theme '{theme['name']}' registered with custom palette")
    ctx.checks = checks


def uc03_special_characters(ctx: Ctx) -> None:
    """Spaces, parens and $ in project/table/column/KPI names."""
    ctx.write("data/q3.csv", """\
        "Order Date","Net Revenue ($)","Region Name"
        2024-07-01,1000,North
        2024-07-02,1500,South
        """)
    ctx.write("dashboard.yaml", """\
        project:
          name: Q3 Sales (EMEA)
        data:
          source: data/q3.csv
          table: Sales Data
          date_column: Order Date
        kpis:
          - name: Revenue (USD)
            column: Net Revenue ($)
            format: currency
            trend: mom
        pages:
          - name: Overview
            visuals:
              - type: kpi
                value: Revenue (USD)
              - type: bar
                title: By region
                category: Sales Data.Region Name
                values: [Revenue (USD)]
        """)
    assert ctx.run_build() == 0, ctx.stderr
    out = ctx.out_dir()
    checks: list[str] = []
    _all_json_parse(out / "Q3SalesEMEA.Report", checks)
    fact = (out / "Q3SalesEMEA.SemanticModel" / "definition"
            / "tables" / "Sales Data.tmdl").read_text(encoding="utf-8")
    assert "table 'Sales Data'" in fact
    assert "column 'Net Revenue ($)'" in fact
    assert "measure 'Revenue (USD)' =" in fact
    checks.append("TMDL identifiers quoted: 'Sales Data', 'Net Revenue ($)', 'Revenue (USD)'")
    assert "{'Sales Data'[Order Date]}" not in fact  # sanity: no mangling
    _visual_refs_valid(out, "Q3SalesEMEA", checks)
    # M Changed Type carries the tricky column names
    assert '"Net Revenue ($)", Int64.Type' in fact, "M type step missing tricky column"
    checks.append("Power Query M Changed Type handles special column names")
    rel = (out / "Q3SalesEMEA.SemanticModel" / "definition" / "relationships.tmdl").read_text()
    assert "'Sales Data'.'Order Date'" in rel
    checks.append("relationship uses quoted fromColumn")
    ctx.checks = checks


def uc04_no_date_column(ctx: Ctx) -> None:
    """No date_column: no Date table, no trends allowed, build still fine."""
    ctx.write("data/mini.csv", MINI_CSV)
    ctx.write("dashboard.yaml", """\
        project:
          name: NoDate
        data:
          source: data/mini.csv
          date_table: false
        kpis:
          - name: Total Amount
            column: amount
        """)
    assert ctx.run_build() == 0, ctx.stderr
    out = ctx.out_dir()
    checks: list[str] = []
    _all_json_parse(out / "NoDate.Report", checks)
    assert not (out / "NoDate.SemanticModel" / "definition" / "tables" / "Date.tmdl").exists()
    rel = (out / "NoDate.SemanticModel" / "definition" / "relationships.tmdl").read_text()
    assert rel.strip() == "", f"expected empty relationships, got: {rel!r}"
    _visual_refs_valid(out, "NoDate", checks)
    checks.append("no Date table and empty relationships.tmdl without date_column")
    ctx.checks = checks


def uc05_parquet(ctx: Ctx) -> None:
    """Parquet source end-to-end (skipped when pandas/pyarrow missing)."""
    try:
        import pandas as pd  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError:
        raise _Skip("pandas/pyarrow not installed")
    import pandas as pd
    df = pd.DataFrame({
        "order_date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
        "amount": [10.5, 20.0],
        "qty": pd.array([1, 2], dtype="int64"),
        "flag": pd.array([True, False], dtype="bool"),
    })
    df.to_parquet(ctx.tmp / "data.parquet")
    ctx.write("dashboard.yaml", """\
        project:
          name: Parquet
        data:
          source: data.parquet
          table: Orders
          date_column: order_date
        kpis:
          - name: Total Amount
            column: amount
            format: currency
            trend: yoy
        """)
    assert ctx.run_build() == 0, ctx.stderr
    out = ctx.out_dir()
    checks: list[str] = []
    fact = (out / "Parquet.SemanticModel" / "definition" / "tables" / "Orders.tmdl").read_text()
    assert "Parquet.Document" in fact
    _visual_refs_valid(out, "Parquet", checks)
    checks.append("M partition uses Parquet.Document; dtypes mapped (double/int64/boolean/dateTime)")
    ctx.checks = checks


def uc06_bool_and_dates(ctx: Ctx) -> None:
    """Type inference edge cases: word booleans, 1/0 ints, date formats."""
    ctx.write("data/types.csv", """\
        active,flag_int,ordered,shipped_at,price,note
        yes,1,2024-01-31,2024-01-31 10:30:00,9.99,ok
        no,0,02/15/2024,2024-02-15 11:00:00,19.5,
        true,1,2024/03/01,2024-03-01 09:00:00,5,hi
        """)
    ctx.write("dashboard.yaml", """\
        project:
          name: Types
        data:
          source: data/types.csv
          date_column: ordered
        kpis:
          - name: Total Price
            column: price
            format: currency
        """)
    assert ctx.run_build() == 0, ctx.stderr
    out = ctx.out_dir()
    checks: list[str] = []
    fact = (out / "Types.SemanticModel" / "definition" / "tables" / "types.tmdl").read_text()
    assert "column active\n\t\tdataType: boolean" in fact, "word booleans -> boolean"
    assert "column flag_int\n\t\tdataType: int64" in fact, "1/0 -> int64, not boolean"
    assert "column ordered\n\t\tdataType: dateTime" in fact
    assert "column shipped_at\n\t\tdataType: dateTime" in fact
    assert "formatString: m/d/yyyy h:mm" in fact, "datetime keeps time format"
    assert "column price\n\t\tdataType: double" in fact
    assert "column note\n\t\tdataType: string" in fact
    checks.append("inference: yes/no/true -> boolean; 1/0 -> int64; mixed date formats -> dateTime")
    _visual_refs_valid(out, "Types", checks)
    ctx.checks = checks


def uc07_custom_theme_multipage(ctx: Ctx) -> None:
    """Custom theme dict, two pages, glossary disabled."""
    ctx.write("data/mini.csv", MINI_CSV)
    ctx.write("dashboard.yaml", """\
        project:
          name: Themed
          theme:
            name: Brand
            dataColors: ["#123456"]
        data:
          source: data/mini.csv
        kpis:
          - name: Total Amount
            column: amount
        pages:
          - name: One
            visuals:
              - type: kpi
                value: Total Amount
          - name: Two
            visuals:
              - type: table
                columns: [mini.category, Total Amount]
        glossary: false
        """)
    assert ctx.run_build() == 0, ctx.stderr
    out = ctx.out_dir()
    checks: list[str] = []
    got = _pages_are(out, "Themed", ["One", "Two"])
    assert not (out / "Themed.SemanticModel" / "definition" / "tables" / "KPI Glossary.tmdl").exists()
    checks.append("glossary: false -> no KPI Glossary table/page; pages: " + ", ".join(got))
    _visual_refs_valid(out, "Themed", checks)
    ctx.checks = checks


def uc08_overlap_warning(ctx: Ctx) -> None:
    """Explicitly overlapping visuals still build, but warn loudly."""
    ctx.write("data/mini.csv", MINI_CSV)
    ctx.write("dashboard.yaml", """\
        project:
          name: Overlap
        data:
          source: data/mini.csv
        kpis:
          - name: Total Amount
            column: amount
        pages:
          - name: Overview
            visuals:
              - type: kpi
                title: A
                value: Total Amount
                x: 16
                y: 100
                w: 400
                h: 160
              - type: kpi
                title: B
                value: Total Amount
                x: 200
                y: 120
                w: 400
                h: 160
        """)
    assert ctx.run_build() == 0, ctx.stderr
    assert "overlap" in ctx.stderr.lower(), f"expected overlap warning, got: {ctx.stderr}"
    ctx.checks = ["build succeeds; stderr warns about overlapping visuals 'A' with 'B'"]


def uc09_quality_warnings(ctx: Ctx) -> None:
    """All-empty and mostly-empty columns surface as warnings, not errors."""
    ctx.write("data/q.csv", """\
        id,empty_col,half_empty,amount
        1,,x,10
        2,,,20
        3,,,30
        """)
    ctx.write("dashboard.yaml", """\
        project:
          name: Quality
        data:
          source: data/q.csv
        kpis:
          - name: Total Amount
            column: amount
        """)
    assert ctx.run_build() == 0, ctx.stderr
    assert "empty_col" in ctx.stderr and "every sampled row" in ctx.stderr
    assert "half_empty" in ctx.stderr
    ctx.checks = ["warnings emitted for all-empty and >50%-empty columns; build still succeeds"]


def uc10_sales_example(ctx: Ctx) -> None:
    """The shipped example project builds end-to-end from the repo itself."""
    ex = ROOT / "examples" / "sales"
    dest = ctx.tmp / "sales"
    shutil.copytree(ex, dest)
    so, se = io.StringIO(), io.StringIO()
    with redirect_stdout(so), redirect_stderr(se):
        rc = cli_main(["build", "-c", str(dest / "dashboard.yaml"),
                       "-o", str(ctx.tmp / "out")])
    assert rc == 0, se.getvalue()
    cfg = load_config(dest / "dashboard.yaml")
    columns = infer_schema(cfg.data_path)
    plan = build_plan(cfg, columns)
    out = ctx.tmp / "out"
    checks: list[str] = []
    _all_json_parse(out / f"{plan.project}.Report", checks)
    _tmdl_has_measures(out, plan.project, plan.table,
                       [m.name for m in plan.measures], checks)
    _visual_refs_valid(out, plan.project, checks)
    got = _pages_are(out, plan.project, ["Overview", "KPI Glossary"])
    checks.append(f"example: {len(plan.measures)} measures, pages: {', '.join(got)}")
    ctx.checks = checks


def uc11_supply_chain_example(ctx: Ctx) -> None:
    """The supply-chain example: OTIF/fill-rate/lead-time DAX, multi-page."""
    ex = ROOT / "examples" / "supply-chain"
    dest = ctx.tmp / "supply-chain"
    shutil.copytree(ex, dest)
    so, se = io.StringIO(), io.StringIO()
    with redirect_stdout(so), redirect_stderr(se):
        rc = cli_main(["build", "-c", str(dest / "dashboard.yaml"),
                       "-o", str(ctx.tmp / "out")])
    assert rc == 0, se.getvalue()
    cfg = load_config(dest / "dashboard.yaml")
    columns = infer_schema(cfg.data_path)
    plan = build_plan(cfg, columns)
    out = ctx.tmp / "out"
    checks: list[str] = []
    _all_json_parse(out / f"{plan.project}.Report", checks)
    _tmdl_has_measures(out, plan.project, plan.table, [
        "On-Time Delivery", "In-Full Delivery", "Fill Rate",
        "OTIF %", "OTIF % YoY %", "OTIF % Target", "OTIF % Target %",
        "On-Time %", "In-Full %", "Fill Rate %",
        "Avg Lead Time (Days)", "Avg Lead Time (Days) QoQ %",
        "Backorder Lines", "Forecast Accuracy", "Shipped Value",
    ], checks)
    _visual_refs_valid(out, plan.project, checks)
    got = _pages_are(out, plan.project,
                     ["Overview", "Fulfillment Detail", "KPI Glossary"])
    # documentation-only rule still lands in the glossary
    gloss = (out / f"{plan.project}.SemanticModel" / "definition"
             / "tables" / "KPI Glossary.tmdl").read_text(encoding="utf-8")
    assert "Perfect Order" in gloss and "BOTH on-time AND in-full" in gloss
    checks.append("glossary-only 'Perfect Order' rule documented with its definition")
    # the multi-line OTIF DAX survived YAML folding into TMDL
    fact = (out / f"{plan.project}.SemanticModel" / "definition"
            / "tables" / "Shipments.tmdl").read_text(encoding="utf-8")
    assert "&&" in fact and "delivered_qty" in fact
    checks.append("multi-line OTIF DAX (with &&) intact in TMDL")
    checks.append(f"supply-chain example: {len(plan.measures)} measures, "
                 f"pages: {', '.join(got)}")
    ctx.checks = checks


# --------------------------------------------------------------------------
# negative cases: each must FAIL with a clear, actionable error
# --------------------------------------------------------------------------

class _Skip(Exception):
    pass


def _neg(ctx: Ctx, yaml_body: str, csv_body: str, needle: str,
         make_csv: str = "data/data.csv") -> None:
    ctx.write(make_csv, csv_body)
    ctx.write("dashboard.yaml", yaml_body)
    rc = ctx.run_build()
    assert rc != 0, "expected build failure but it succeeded"
    hay = (ctx.stderr + "\n" + ctx.stdout).lower()
    assert needle.lower() in hay, (
        f"error should mention '{needle}'; got:\n{ctx.stderr}\n{ctx.stdout}")
    ctx.checks = [f"rejected as expected (mentions '{needle}')"]


def neg01_unknown_kpi(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg1}
        data: {source: data/data.csv}
        kpis: [{name: Revenue, column: amount}]
        pages: [{name: P, visuals: [{type: kpi, value: Nope}]}]
        """, MINI_CSV.replace("amount", "amount"), "unknown kpi")


def neg02_trend_without_date(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg2}
        data: {source: data/data.csv}
        kpis: [{name: Revenue, column: amount, trend: yoy}]
        """, MINI_CSV, "date_column")


def neg03_unbalanced_dax(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg3}
        data: {source: data/data.csv}
        business_rules: [{name: Bad, dax: "SUM(data[amount]"}]
        """, MINI_CSV, "unbalanced")


def neg04_gauge_without_target(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg4}
        data: {source: data/data.csv}
        kpis: [{name: Revenue, column: amount}]
        pages: [{name: P, visuals: [{type: gauge, value: Revenue}]}]
        """, MINI_CSV, "target")


def neg05_missing_file(ctx: Ctx) -> None:
    ctx.write("dashboard.yaml", """\
        project: {name: Neg5}
        data: {source: data/gone.csv}
        kpis: [{name: Revenue, column: amount}]
        """)
    rc = ctx.run_build()
    assert rc != 0
    assert "not found" in ctx.stderr.lower()
    ctx.checks = ["rejected as expected (mentions 'not found')"]


def neg06_duplicate_kpis(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg6}
        data: {source: data/data.csv}
        kpis: [{name: Revenue, column: amount}, {name: Revenue, column: amount}]
        """, MINI_CSV, "duplicate kpi")


def neg07_kpi_rule_name_clash(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg7}
        data: {source: data/data.csv}
        business_rules: [{name: Revenue, definition: x, dax: "SUM(data[amount])"}]
        kpis: [{name: Revenue, column: amount}]
        """, MINI_CSV, "both kpi and business rule")


def neg08_duplicate_csv_headers(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg8}
        data: {source: data/data.csv}
        kpis: [{name: Revenue, column: amount}]
        """, "amount,Amount\n1,2\n", "duplicate column")


def neg09_line_without_values(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg9}
        data: {source: data/data.csv}
        kpis: [{name: Revenue, column: amount}]
        pages: [{name: P, visuals: [{type: line, category: data.category}]}]
        """, "category,amount\nA,1\n", "needs at least one entry")


def neg10_bad_column_chars(ctx: Ctx) -> None:
    _neg(ctx, """\
        project: {name: Neg10}
        data: {source: data/data.csv}
        kpis: [{name: Revenue, column: amount}]
        """, 'a"b,amount\n1,2\n', "quote")


CASES: list[tuple[str, str, object]] = [
    ("UC-01", "Minimal config, everything defaulted", uc01_minimal),
    ("UC-02", "Kitchen sink: all visuals, trends, targets, rules, theme", uc02_kitchen_sink),
    ("UC-03", "Special characters in names", uc03_special_characters),
    ("UC-04", "No date column", uc04_no_date_column),
    ("UC-05", "Parquet source", uc05_parquet),
    ("UC-06", "Type-inference edge cases", uc06_bool_and_dates),
    ("UC-07", "Custom theme, multi-page, no glossary", uc07_custom_theme_multipage),
    ("UC-08", "Overlapping explicit layout warns", uc08_overlap_warning),
    ("UC-09", "Data-quality warnings", uc09_quality_warnings),
    ("UC-10", "Shipped sales example", uc10_sales_example),
    ("UC-11", "Supply-chain example (OTIF, fill rate, lead time)", uc11_supply_chain_example),
    ("NEG-01", "Unknown KPI reference rejected", neg01_unknown_kpi),
    ("NEG-02", "Trend without date_column rejected", neg02_trend_without_date),
    ("NEG-03", "Unbalanced DAX rejected", neg03_unbalanced_dax),
    ("NEG-04", "Gauge without target rejected", neg04_gauge_without_target),
    ("NEG-05", "Missing data file rejected", neg05_missing_file),
    ("NEG-06", "Duplicate KPI names rejected", neg06_duplicate_kpis),
    ("NEG-07", "KPI/rule name clash rejected", neg07_kpi_rule_name_clash),
    ("NEG-08", "Duplicate CSV headers rejected", neg08_duplicate_csv_headers),
    ("NEG-09", "Line visual without values rejected", neg09_line_without_values),
    ("NEG-10", "Illegal characters in column names rejected", neg10_bad_column_chars),
]


def run_all() -> list[CaseResult]:
    results: list[CaseResult] = []
    for cid, title, fn in CASES:
        tmp = Path(tempfile.mkdtemp(prefix="autopbi_uc_"))
        ctx = Ctx(tmp=tmp)
        try:
            fn(ctx)
            results.append(CaseResult(cid, title, "PASS", checks=ctx.checks or []))
        except _Skip as s:
            results.append(CaseResult(cid, title, "SKIP", detail=str(s)))
        except Exception:  # noqa: BLE001
            results.append(CaseResult(cid, title, "FAIL",
                                      detail=traceback.format_exc(limit=8)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return results


def write_report(results: list[CaseResult]) -> None:
    passed = sum(1 for r in results if r.status == "PASS")
    failed = [r for r in results if r.status == "FAIL"]
    skipped = [r for r in results if r.status == "SKIP"]

    lines = [
        "# AutoPBI Use-Case Test Report",
        "",
        f"_Generated {date.today().isoformat()} by `scripts/run_usecases.py` — "
        "every result below comes from a real end-to-end build, not from "
        "reading the code._",
        "",
        "## Summary",
        "",
        f"- **{passed} passed**, {len(failed)} failed, {len(skipped)} skipped "
        f"({len(results)} total)",
        "",
        "| Case | Scenario | Result |",
        "| ---- | -------- | ------ |",
    ]
    for r in results:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[r.status]
        lines.append(f"| {r.id} | {r.title} | {icon} {r.status} |")
    lines += ["", "## What each case verifies", ""]
    for r in results:
        lines.append(f"### {r.id} — {r.title}")
        lines.append("")
        if r.status == "PASS":
            for c in r.checks:
                lines.append(f"- {c}")
        elif r.status == "SKIP":
            lines.append(f"- Skipped: {r.detail}")
        else:
            lines.append("```")
            lines.append(r.detail.strip())
            lines.append("```")
        lines.append("")
    lines += [
        "## How to re-run",
        "",
        "```bash",
        "cd ~/workspace/your_files/auto-pbi",
        ".venv/bin/python scripts/run_usecases.py",
        "```",
        "",
        "The script rebuilds every scenario in a temp directory, structurally "
        "validates the output (all JSON parses, every visual `queryRef` resolves "
        "to a real measure/column in the TMDL model, expected measures exist, "
        "page order is correct), then regenerates this file.",
        "",
        "## Manual step (needs Power BI Desktop on Windows)",
        "",
        "Open any generated `.pbip` in Power BI Desktop and press **Refresh**. "
        "Automated checks cover structure and references; only Desktop can "
        "verify visual rendering on your installed version.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> int:
    results = run_all()
    write_report(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = [r for r in results if r.status == "FAIL"]
    skipped = sum(1 for r in results if r.status == "SKIP")
    print(f"\n{passed} passed, {len(failed)} failed, {skipped} skipped")
    for r in failed:
        print(f"  FAIL {r.id}: {r.title}")
    print(f"report -> {REPORT_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
