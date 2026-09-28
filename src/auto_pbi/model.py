"""TMDL semantic-model builder.

Writes `<Project>.SemanticModel/`:
    definition.pbism
    definition/database.tmdl
    definition/model.tmdl
    definition/cultures/en-US.tmdl
    definition/tables/<Table>.tmdl        (fact table: columns + measures + M partition)
    definition/tables/Date.tmdl           (DAX calculated date table, optional)
    definition/tables/KPI Glossary.tmdl   (DAX DATATABLE, optional)
    definition/relationships.tmdl

Conventions follow the PBIP/TMDL format: tab indentation, UTF-8 no BOM,
single-quoted identifiers when they contain spaces.
"""

from __future__ import annotations

import re
from pathlib import Path

from .infer import ColumnInfo
from .plan import BuildPlan, MeasurePlan

COMPATIBILITY_LEVEL = 1567


def tid(name: str) -> str:
    """Quote a TMDL identifier if it needs it."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        return name
    return "'" + name.replace("'", "''") + "'"


def _tref(table: str, column: str) -> str:
    return f"{tid(table)}.{tid(column)}"


def _m_str(name: str) -> str:
    """Quote a name as an M text literal (embedded quotes are doubled)."""
    return '"' + name.replace('"', '""') + '"'


def _m_expression(plan: BuildPlan) -> list[str]:
    """Power Query M source for the fact table partition."""
    path = str(plan.data_path)
    if plan.source_kind == "parquet":
        return [
            "let",
            f"\tSource = Parquet.Document(File.Contents(\"{path}\"))",
            "in",
            "\tSource",
        ]
    cols = str(len(plan.columns))
    changed = ", ".join(f"{{{_m_str(c.name)}, {c.m_type}}}" for c in plan.columns)
    return [
        "let",
        f"\tSource = Csv.Document(File.Contents(\"{path}\"), "
        f"[Delimiter=\",\", Columns={cols}, Encoding=65001, QuoteStyle=QuoteStyle.None]),",
        "\t#\"Promoted Headers\" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        f"\t#\"Changed Type\" = Table.TransformColumnTypes(#\"Promoted Headers\", {{{changed}}})",
        "in",
        "\t#\"Changed Type\"",
    ]


def _sanitize_dax_text(s: str) -> str:
    return s.replace('"', "'").replace("\r", " ").replace("\n", " ").strip()


def _fact_table_tmdl(plan: BuildPlan) -> str:
    L: list[str] = [f"table {tid(plan.table)}", ""]
    for c in plan.columns:
        L.append(f"\tcolumn {tid(c.name)}")
        L.append(f"\t\tdataType: {c.tmdl_type}")
        if c.tmdl_type == "dateTime":
            L.append("\t\tformatString: m/d/yyyy" if c.date_only else "\t\tformatString: m/d/yyyy h:mm")
        L.append("\t\tsummarizeBy: none")
        L.append(f"\t\tsourceColumn: {tid(c.name)}")
        L.append("")
    for m in plan.measures:
        L.extend(_measure_block(m))
    L.append(f"\tpartition {tid(plan.table)} = m")
    L.append("\t\tmode: import")
    L.append("\t\tsource =")
    for line in _m_expression(plan):
        L.append(f"\t\t\t{line}" if line else "")
    L.append("")
    return "\n".join(L)


def _measure_block(m: MeasurePlan) -> list[str]:
    L = [f"\tmeasure {tid(m.name)} ="]
    for line in m.dax.splitlines():
        L.append(f"\t\t{line}" if line.strip() else "")
    L.append(f"\t\tformatString: {m.format}")
    if m.description:
        L.append(f"\t\tdescription: {_sanitize_dax_text(m.description)}")
    if m.folder:
        L.append(f"\t\tdisplayFolder: {m.folder}")
    L.append("")
    return L


def _date_table_tmdl(plan: BuildPlan) -> str:
    date_ref = f"{tid(plan.table)}[{plan.date_column}]"
    dax_lines = [
        f"VAR _min = MIN({date_ref})",
        f"VAR _max = MAX({date_ref})",
        "RETURN",
        "ADDCOLUMNS(",
        "\tCALENDAR(_min, _max),",
        '\t"Year", YEAR([Date]),',
        '\t"Quarter", "Q" & FORMAT([Date], "q"),',
        '\t"Month", FORMAT([Date], "mmm yyyy"),',
        '\t"Month Key", FORMAT([Date], "yyyy-mm"),',
        '\t"Month Number", MONTH([Date]),',
        '\t"Year-Month Number", YEAR([Date]) * 100 + MONTH([Date]),',
        '\t"Day", DAY([Date])',
        ")",
    ]
    cols = [
        # (name, tmdl_type, format, is_key, sort_by)
        ("Date", "dateTime", "m/d/yyyy", True, None),
        ("Year", "int64", None, False, None),
        ("Quarter", "string", None, False, None),
        ("Month", "string", None, False, "Month Key"),
        ("Month Key", "string", None, False, None),
        ("Month Number", "int64", None, False, None),
        ("Year-Month Number", "int64", None, False, None),
        ("Day", "int64", None, False, None),
    ]
    L = ["table Date", ""]
    for name, dtype, fmt, is_key, sort_by in cols:
        L.append(f"\tcolumn {tid(name)}")
        L.append(f"\t\tdataType: {dtype}")
        if fmt:
            L.append(f"\t\tformatString: {fmt}")
        if is_key:
            L.append("\t\tisKey")
        if sort_by:
            L.append(f"\t\tsortByColumn: {tid(sort_by)}")
        L.append("\t\tsummarizeBy: none")
        L.append(f"\t\tsourceColumn: {tid(name)}")
        L.append("")
    L.append("\tpartition Date = calculated")
    L.append("\t\tmode: import")
    L.append("\t\tsource =")
    for line in dax_lines:
        L.append(f"\t\t\t{line}" if line else "")
    L.append("")
    return "\n".join(L)


def _glossary_table_tmdl(plan: BuildPlan) -> str:
    rows = []
    for name, definition, dax_expr in plan.glossary_rows:
        rows.append(
            "\t\t\t{\"" + _sanitize_dax_text(name) + "\", "
            + "\"" + _sanitize_dax_text(definition or "—") + "\", "
            + "\"" + _sanitize_dax_text(dax_expr or "—") + "\"},"
        )
    if rows:
        rows[-1] = rows[-1].rstrip(",")
    dax_lines = [
        "DATATABLE(",
        '\t"KPI", STRING,',
        '\t"Definition", STRING,',
        '\t"DAX Expression", STRING,',
        "\t{",
        *rows,
        "\t}",
        ")",
    ]
    L = ["table 'KPI Glossary'", ""]
    for name in ("KPI", "Definition", "DAX Expression"):
        L.append(f"\tcolumn {tid(name)}")
        L.append("\t\tdataType: string")
        L.append("\t\tsummarizeBy: none")
        L.append(f"\t\tsourceColumn: {tid(name)}")
        L.append("")
    L.append("\tpartition 'KPI Glossary' = calculated")
    L.append("\t\tmode: import")
    L.append("\t\tsource =")
    for line in dax_lines:
        L.append(f"\t\t\t{line}" if line else "")
    L.append("")
    return "\n".join(L)


def _relationships_tmdl(plan: BuildPlan) -> str:
    L: list[str] = []
    for i, (frm, to) in enumerate(plan.relationships):
        ftable, fcol = frm.split(".", 1)
        ttable, tcol = to.split(".", 1)
        L.append(f"relationship {tid(f'rel_{i}_{ftable}_{fcol}')}")
        L.append(f"\tfromColumn: {_tref(ftable, fcol)}")
        L.append(f"\ttoColumn: {_tref(ttable, tcol)}")
        L.append("")
    return "\n".join(L)


def write_semantic_model(plan: BuildPlan, out_dir: Path) -> Path:
    """Write the .SemanticModel folder. Returns its path."""
    sm = out_dir / f"{plan.project}.SemanticModel"
    definition = sm / "definition"
    (definition / "tables").mkdir(parents=True, exist_ok=True)
    (definition / "cultures").mkdir(parents=True, exist_ok=True)

    def w(rel: str, content: str) -> None:
        p = definition / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")

    (sm / "definition.pbism").write_text(
        '{\n  "version": "1.0",\n  "datasetReference": {\n'
        '    "byPath": null,\n    "byConnection": null\n  }\n}\n',
        encoding="utf-8", newline="\n")

    w("database.tmdl", f"database {tid(plan.project)}\n\tcompatibilityLevel: {COMPATIBILITY_LEVEL}\n")
    w("model.tmdl",
      "model Model\n"
      "\tculture: en-US\n"
      "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
      "\tdiscourageImplicitMeasures: true\n"
      "\tsourceQueryCulture: en-US\n")
    w("cultures/en-US.tmdl", "culture en-US\n")
    w(f"tables/{plan.table}.tmdl", _fact_table_tmdl(plan))
    if plan.date_table:
        w("tables/Date.tmdl", _date_table_tmdl(plan))
    if plan.glossary_rows:
        w("tables/KPI Glossary.tmdl", _glossary_table_tmdl(plan))
    w("relationships.tmdl", _relationships_tmdl(plan))
    return sm
