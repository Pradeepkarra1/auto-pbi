"""AutoPBI command line interface.

    auto-pbi init <name> [--dir .]      scaffold a starter project
    auto-pbi build -c dashboard.yaml [-o ./out]   generate the .pbip project
    auto-pbi validate -c dashboard.yaml           check config + data without writing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .infer import infer_schema, quality_warnings
from .model import write_semantic_model
from .plan import build_plan
from .report import write_report
from .theme import resolve_theme

INIT_TEMPLATE = """# AutoPBI dashboard definition.
# Full reference: docs/CONFIG_REFERENCE.md

project:
  name: {name}
  description: "Describe what this dashboard is for."
  theme: midnight            # midnight | corporate | forest | sunset (or a custom mapping)

data:
  source: data/my_data.csv   # clean CSV or Parquet, relative to this file
  # table: MyTable           # defaults to the file name
  # date_column: order_date  # enables the Date table + YoY/MoM/QoQ trends
  # date_table: true

business_rules:
  - name: Net Revenue
    definition: Gross sales minus refunds and discounts.
    dax: SUM('MyTable'[gross]) - SUM('MyTable'[refunds])

kpis:
  - name: Total Revenue
    description: Net revenue for the selected period.
    rule: Net Revenue        # build on a business rule...
    # column: net_revenue    # ...or aggregate a column directly
    # aggregation: sum
    # dax: "..."             # ...or drop in raw DAX
    format: currency
    target: 1000000
    trend: yoy               # none | yoy | mom | qoq (needs data.date_column)

pages:
  - name: Overview
    visuals:
      - type: kpi_row        # one card per KPI (or list kpis: [...] explicitly)
      - type: line
        title: Revenue trend
        category: Date.Month # Table.Column, or a KPI name for measures
        values: [Total Revenue]
      - type: bar
        title: Revenue by region
        category: MyTable.region
        values: [Total Revenue]
      - type: table
        title: Detail
        columns: [MyTable.order_id, MyTable.order_date, Total Revenue]

glossary: true               # auto-generate a KPI Glossary page
"""


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.dir or ".") / args.name
    target.mkdir(parents=True, exist_ok=True)
    (target / "data").mkdir(exist_ok=True)
    yaml_path = target / "dashboard.yaml"
    if yaml_path.exists() and not args.force:
        print(f"error: {yaml_path} already exists (use --force to overwrite)",
              file=sys.stderr)
        return 1
    yaml_path.write_text(INIT_TEMPLATE.format(name=args.name), encoding="utf-8")
    (target / "data" / ".gitkeep").write_text("", encoding="utf-8")
    print(f"Created {yaml_path}")
    print("Next: drop your clean CSV into data/, edit dashboard.yaml, then run:")
    print(f"  auto-pbi build --config {yaml_path} --out ./out")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        data_path = cfg.data_path
        if not data_path.exists():
            raise ConfigError(f"Data file not found: {data_path}")
        columns = infer_schema(data_path)
        plan = build_plan(cfg, columns)
    except (ConfigError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in quality_warnings(data_path, columns):
        print(f"warning: {w}", file=sys.stderr)
    print(f"Config OK: {args.config}")
    print(f"  project : {plan.project}")
    print(f"  data    : {data_path} ({len(columns)} columns, {plan.source_kind})")
    print(f"  table   : {plan.table}")
    print(f"  measures: {len(plan.measures)}")
    for m in plan.measures:
        print(f"    - {m.name}")
    if plan.date_table:
        print(f"  date tbl: Date (joined on {plan.table}.{plan.date_column})")
    print(f"  pages   : {len(cfg.pages) or 1} (glossary: {'yes' if plan.glossary_rows else 'no'})")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        data_path = cfg.data_path
        if not data_path.exists():
            raise ConfigError(f"Data file not found: {data_path}")
        columns = infer_schema(data_path)
        plan = build_plan(cfg, columns)
        for w in quality_warnings(data_path, columns):
            print(f"warning: {w}", file=sys.stderr)

        theme_name, theme = resolve_theme(cfg.project.theme, plan.project)
        out = Path(args.out or ".").resolve()
        out.mkdir(parents=True, exist_ok=True)

        pbip = {
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{plan.project}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        }
        with open(out / f"{plan.project}.pbip", "w", encoding="utf-8", newline="\n") as f:
            json.dump(pbip, f, indent=2)
            f.write("\n")

        sm = write_semantic_model(plan, out)
        rep = write_report(cfg, plan, out, theme_name, theme)
    except (ConfigError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    n_visuals = sum(len(list((rep / "definition" / "pages" / p / "visuals").iterdir()))
                    for p in (rep / "definition" / "pages").iterdir() if p.is_dir())
    print(f"Built {plan.project}.pbip -> {out}")
    print(f"  semantic model: {sm.name} ({len(plan.measures)} measures)")
    print(f"  report        : {rep.name}")
    print(f"  theme         : {theme_name}")
    print()
    print("Open it: Power BI Desktop -> File -> Open -> select the .pbip file,")
    print("then press Refresh so the model loads your data.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="auto-pbi", description=__doc__)
    p.add_argument("--version", action="version", version=f"auto-pbi {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="Scaffold a starter dashboard project.")
    i.add_argument("name", help="Project name, e.g. SalesPerformance")
    i.add_argument("--dir", default=".", help="Parent directory (default: .)")
    i.add_argument("--force", action="store_true")
    i.set_defaults(fn=cmd_init)

    v = sub.add_parser("validate", help="Validate config + data without writing files.")
    v.add_argument("-c", "--config", required=True, help="Path to dashboard.yaml")
    v.set_defaults(fn=cmd_validate)

    b = sub.add_parser("build", help="Generate the .pbip project.")
    b.add_argument("-c", "--config", required=True, help="Path to dashboard.yaml")
    b.add_argument("-o", "--out", default=".", help="Output directory (default: .)")
    b.set_defaults(fn=cmd_build)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
