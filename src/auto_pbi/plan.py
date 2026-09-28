"""Build planning: turn dashboard.yaml + inferred schema into a concrete plan.

The plan is the shared contract between the TMDL model builder and the
PBIR report builder — every measure, relationship and glossary row is
decided exactly once, up front.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import dax
from .config import ConfigError, DashboardConfig
from .infer import ColumnInfo


@dataclass
class MeasurePlan:
    name: str
    dax: str
    format: str
    description: str = ""
    folder: str = "KPIs"


@dataclass
class BuildPlan:
    project: str            # safe folder name, e.g. SalesPerformance
    table: str              # fact table name
    columns: list[ColumnInfo]
    measures: list[MeasurePlan]
    glossary_rows: list[tuple[str, str, str]]  # (name, definition, dax)
    date_table: bool
    date_column: str
    relationships: list[tuple[str, str]]       # (from Table.Column, to Table.Column)
    data_path: Path
    source_kind: str        # "csv" | "parquet"

    def measure_names(self) -> set[str]:
        return {m.name for m in self.measures}

    def column_names(self) -> set[str]:
        return {c.name for c in self.columns}


def build_plan(cfg: DashboardConfig, columns: list[ColumnInfo]) -> BuildPlan:
    table = cfg.data.table or Path(cfg.data.source).stem
    if not table:
        raise ConfigError("Could not determine a table name; set data.table explicitly.")
    if any(ch in table for ch in '/\\'):
        raise ConfigError(
            f"data.table '{table}' must not contain path separators.")
    col_names = {c.name for c in columns}
    for c in columns:
        if any(ch in c.name for ch in '"\r\n\t'):
            raise ConfigError(
                f"Column '{c.name}' contains a quote, tab or newline, which the "
                f"generated TMDL / Power Query M cannot represent. Rename the column.")
    if cfg.data.date_column and cfg.data.date_column not in col_names:
        raise ConfigError(
            f"data.date_column '{cfg.data.date_column}' not found in "
            f"{cfg.data.source}. Columns: {sorted(col_names)}")

    measures: list[MeasurePlan] = []
    glossary: list[tuple[str, str, str]] = []
    rule_dax: dict[str, str] = {}

    def _add(m: MeasurePlan) -> None:
        if m.name in {x.name for x in measures}:
            raise ConfigError(
                f"Duplicate measure name '{m.name}'. KPI, rule, trend and target "
                f"names must not collide with each other.")
        measures.append(m)

    for rule in cfg.business_rules:
        if rule.dax:
            if not dax.check_balanced(rule.dax):
                raise ConfigError(f"Business rule '{rule.name}': DAX has unbalanced brackets.")
            rule_dax[rule.name] = rule.dax
            _add(MeasurePlan(
                name=rule.name, dax=rule.dax, format="#,##0.00",
                description=rule.definition, folder="Business Rules"))
        glossary.append((rule.name, rule.definition, rule.dax))

    for kpi in cfg.kpis:
        if kpi.rule and kpi.rule not in rule_dax:
            raise ConfigError(
                f"KPI '{kpi.name}': business rule '{kpi.rule}' has no DAX expression "
                f"to build on. Add 'dax:' to the rule.")
        if kpi.column and kpi.column not in col_names:
            raise ConfigError(
                f"KPI '{kpi.name}': column '{kpi.column}' not found in {cfg.data.source}.")
        base_dax, fmt = dax.base_measure(kpi, table, rule_dax)
        if not dax.check_balanced(base_dax):
            raise ConfigError(f"KPI '{kpi.name}': DAX has unbalanced brackets.")
        _add(MeasurePlan(
            name=kpi.name, dax=base_dax, format=fmt,
            description=kpi.description, folder="KPIs"))
        glossary.append((kpi.name, kpi.description, base_dax))

        if kpi.trend == "yoy":
            _add(MeasurePlan(
                name=f"{kpi.name} YoY %", dax=dax.yoy_growth(kpi.name),
                format="0.0%", description=f"Year-over-year change of {kpi.name}.",
                folder="Time Intelligence"))
        elif kpi.trend == "mom":
            _add(MeasurePlan(
                name=f"{kpi.name} MoM %", dax=dax.mom_growth(kpi.name),
                format="0.0%", description=f"Month-over-month change of {kpi.name}.",
                folder="Time Intelligence"))
        elif kpi.trend == "qoq":
            _add(MeasurePlan(
                name=f"{kpi.name} QoQ %", dax=dax.qoq_growth(kpi.name),
                format="0.0%", description=f"Quarter-over-quarter change of {kpi.name}.",
                folder="Time Intelligence"))

        if kpi.target is not None:
            _add(MeasurePlan(
                name=f"{kpi.name} Target", dax=f"{kpi.target}",
                format=fmt, description=f"Target for {kpi.name}.", folder="Targets"))
            _add(MeasurePlan(
                name=f"{kpi.name} vs Target", dax=dax.vs_target(kpi.name),
                format=fmt, description=f"{kpi.name} minus target.", folder="Targets"))
            _add(MeasurePlan(
                name=f"{kpi.name} Target %", dax=dax.target_achievement(kpi.name),
                format="0.0%", description=f"{kpi.name} as a percentage of target.",
                folder="Targets"))

    # numeric gauge targets become measures too
    for page in cfg.pages:
        for v in page.visuals:
            if v.type == "gauge" and v.target is not None:
                base = next((k for k in cfg.kpis if k.name == v.value), None)
                if base is None:
                    continue
                _, fmt = dax.base_measure(base, table, rule_dax)
                tname = f"{v.title or v.value} Target"
                if tname not in {m.name for m in measures}:
                    _add(MeasurePlan(
                        name=tname, dax=f"{v.target}", format=fmt,
                        description=f"Gauge target for {v.title or v.value}.",
                        folder="Targets"))

    date_table = bool(cfg.data.date_column and cfg.data.date_table)
    relationships: list[tuple[str, str]] = []
    if date_table:
        relationships.append((f"{table}.{cfg.data.date_column}", "Date.Date"))

    suffix = Path(cfg.data.source).suffix.lower()
    return BuildPlan(
        project=cfg.project.safe_name,
        table=table,
        columns=columns,
        measures=measures,
        glossary_rows=glossary if (cfg.glossary and glossary) else [],
        date_table=date_table,
        date_column=cfg.data.date_column,
        relationships=relationships,
        data_path=cfg.data_path,
        source_kind="parquet" if suffix in (".parquet", ".pq") else "csv",
    )
