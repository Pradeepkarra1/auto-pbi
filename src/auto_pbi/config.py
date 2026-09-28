"""Load and validate the dashboard YAML configuration.

The config is the single source of truth for a build:

    project:        name / description / theme
    data:           clean source file, table name, date column
    business_rules: named definitions (+ optional DAX) -> model measures + glossary
    kpis:           named metrics -> DAX measures (+ YoY/MoM, targets)
    pages:          report pages and their visuals
    glossary:       auto-generate a KPI Glossary page (default: true)

See docs/CONFIG_REFERENCE.md for the full spec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

AGGREGATIONS = {"sum", "avg", "min", "max", "count", "distinct_count"}
TRENDS = {"none", "yoy", "mom", "qoq"}
FORMATS = {"currency", "percent", "number", "decimal", "integer"}
VISUAL_TYPES = {
    "kpi_row", "kpi", "line", "bar", "column", "area", "donut", "pie",
    "table", "matrix", "slicer", "gauge", "textbox",
}


class ConfigError(ValueError):
    """Raised when dashboard.yaml is invalid."""


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return slug or "page"


@dataclass
class ProjectConfig:
    name: str
    description: str = ""
    theme: Any = "midnight"

    @property
    def safe_name(self) -> str:
        """PascalCase-ish name used for .pbip folders (no spaces)."""
        parts = re.split(r"[^A-Za-z0-9]+", self.name)
        safe = "".join(p[:1].upper() + p[1:] for p in parts if p)
        return safe or "Dashboard"


@dataclass
class DataConfig:
    source: str
    table: str = ""
    date_column: str = ""
    date_table: bool = True


@dataclass
class BusinessRule:
    name: str
    definition: str = ""
    dax: str = ""  # optional raw DAX; becomes a measure when present


@dataclass
class KpiConfig:
    name: str
    description: str = ""
    column: str = ""        # base column on the fact table
    rule: str = ""          # ...or a business rule name to build on
    aggregation: str = "sum"
    dax: str = ""           # raw DAX override (wins over column/aggregation)
    format: str = "number"
    target: Optional[float] = None
    trend: str = "none"     # none|yoy|mom|qoq
    show_card: bool = True


@dataclass
class VisualConfig:
    type: str
    title: str = ""
    kpis: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)   # matrix rows
    category: str = ""
    series: str = ""
    field: str = ""
    value: str = ""
    target: Optional[float] = None
    text: str = ""
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None


@dataclass
class PageConfig:
    name: str
    visuals: list[VisualConfig] = field(default_factory=list)


@dataclass
class DashboardConfig:
    project: ProjectConfig
    data: DataConfig
    business_rules: list[BusinessRule]
    kpis: list[KpiConfig]
    pages: list[PageConfig]
    glossary: bool
    config_dir: Path

    @property
    def data_path(self) -> Path:
        p = Path(self.data.source)
        return p if p.is_absolute() else (self.config_dir / p).resolve()

    def kpi_names(self) -> set[str]:
        return {k.name for k in self.kpis}

    def rule_names(self) -> set[str]:
        return {r.name for r in self.business_rules}


def _req(mapping: dict, key: str, ctx: str) -> Any:
    if key not in mapping or mapping[key] is None:
        raise ConfigError(f"Missing required key '{key}' in {ctx}.")
    return mapping[key]


def load_config(path: str | Path) -> DashboardConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ConfigError("Top level of dashboard.yaml must be a mapping.")

    # --- project ---
    praw = raw.get("project") or {}
    project = ProjectConfig(
        name=str(_req(praw, "name", "project")),
        description=str(praw.get("description") or ""),
        theme=praw.get("theme", "midnight"),
    )

    # --- data ---
    draw = raw.get("data") or {}
    source = str(_req(draw, "source", "data"))
    data = DataConfig(
        source=source,
        table=str(draw.get("table") or ""),
        date_column=str(draw.get("date_column") or ""),
        date_table=bool(draw.get("date_table", True)),
    )

    # --- business rules ---
    rules: list[BusinessRule] = []
    for i, r in enumerate(raw.get("business_rules") or []):
        if not isinstance(r, dict):
            raise ConfigError(f"business_rules[{i}] must be a mapping.")
        rules.append(BusinessRule(
            name=str(_req(r, "name", f"business_rules[{i}]")),
            definition=str(r.get("definition") or ""),
            dax=str(r.get("dax") or "").strip(),
        ))

    # --- kpis ---
    kpis: list[KpiConfig] = []
    for i, k in enumerate(raw.get("kpis") or []):
        if not isinstance(k, dict):
            raise ConfigError(f"kpis[{i}] must be a mapping.")
        agg = str(k.get("aggregation", "sum")).lower()
        trend = str(k.get("trend", "none")).lower()
        fmt = str(k.get("format", "number")).lower()
        if agg not in AGGREGATIONS:
            raise ConfigError(f"kpis[{i}] '{k.get('name')}': unknown aggregation '{agg}'. "
                              f"Choose from {sorted(AGGREGATIONS)}.")
        if trend not in TRENDS:
            raise ConfigError(f"kpis[{i}] '{k.get('name')}': unknown trend '{trend}'. "
                              f"Choose from {sorted(TRENDS)}.")
        if fmt not in FORMATS:
            raise ConfigError(f"kpis[{i}] '{k.get('name')}': unknown format '{fmt}'. "
                              f"Choose from {sorted(FORMATS)}.")
        tgt = k.get("target")
        kpis.append(KpiConfig(
            name=str(_req(k, "name", f"kpis[{i}]")),
            description=str(k.get("description") or ""),
            column=str(k.get("column") or ""),
            rule=str(k.get("rule") or ""),
            aggregation=agg,
            dax=str(k.get("dax") or "").strip(),
            format=fmt,
            target=float(tgt) if tgt is not None else None,
            trend=trend,
            show_card=bool(k.get("show_card", True)),
        ))

    # --- pages ---
    pages: list[PageConfig] = []
    for i, p in enumerate(raw.get("pages") or []):
        if not isinstance(p, dict):
            raise ConfigError(f"pages[{i}] must be a mapping.")
        visuals: list[VisualConfig] = []
        for j, v in enumerate(p.get("visuals") or []):
            if not isinstance(v, dict):
                raise ConfigError(f"pages[{i}].visuals[{j}] must be a mapping.")
            vtype = str(_req(v, "type", f"pages[{i}].visuals[{j}]")).lower()
            if vtype not in VISUAL_TYPES:
                raise ConfigError(f"pages[{i}].visuals[{j}]: unknown visual type '{vtype}'. "
                                  f"Choose from {sorted(VISUAL_TYPES)}.")
            visuals.append(VisualConfig(
                type=vtype,
                title=str(v.get("title") or ""),
                kpis=[str(x) for x in (v.get("kpis") or [])],
                values=[str(x) for x in (v.get("values") or [])],
                columns=[str(x) for x in (v.get("columns") or [])],
                rows=[str(x) for x in (v.get("rows") or [])],
                category=str(v.get("category") or ""),
                series=str(v.get("series") or ""),
                field=str(v.get("field") or ""),
                value=str(v.get("value") or ""),
                target=float(v["target"]) if v.get("target") is not None else None,
                text=str(v.get("text") or ""),
                x=v.get("x"), y=v.get("y"), w=v.get("w"), h=v.get("h"),
            ))
        pages.append(PageConfig(name=str(_req(p, "name", f"pages[{i}]")), visuals=visuals))

    glossary = bool(raw.get("glossary", True))

    cfg = DashboardConfig(
        project=project, data=data, business_rules=rules,
        kpis=kpis, pages=pages, glossary=glossary,
        config_dir=path.parent.resolve(),
    )
    _cross_validate(cfg)
    return cfg


def _cross_validate(cfg: DashboardConfig) -> None:
    """Check that names referenced across sections actually exist."""
    kpi_names = cfg.kpi_names()
    rule_names = cfg.rule_names()

    def _dupes(names: list[str]) -> list[str]:
        seen: set[str] = set()
        return sorted({n for n in names if n in seen or seen.add(n)})

    if dupes := _dupes([k.name for k in cfg.kpis]):
        raise ConfigError(f"Duplicate KPI names: {dupes}. Each KPI name becomes a DAX "
                          f"measure and must be unique.")
    if dupes := _dupes([r.name for r in cfg.business_rules]):
        raise ConfigError(f"Duplicate business rule names: {dupes}.")
    if dupes := _dupes([p.name for p in cfg.pages]):
        raise ConfigError(f"Duplicate page names: {dupes}.")
    if clash := sorted(kpi_names & rule_names):
        raise ConfigError(f"Names used as both KPI and business rule: {clash}. "
                          f"Each becomes a model measure and must be unique.")

    for k in cfg.kpis:
        if k.rule and k.rule not in rule_names:
            raise ConfigError(f"KPI '{k.name}' references unknown business rule '{k.rule}'.")
        if k.rule and k.column:
            raise ConfigError(f"KPI '{k.name}': set either 'column' or 'rule', not both.")
        if not k.dax and not k.column and not k.rule:
            raise ConfigError(
                f"KPI '{k.name}': needs one of 'dax', 'column' (+ aggregation) or 'rule'.")
        if k.trend != "none" and not cfg.data.date_column:
            raise ConfigError(
                f"KPI '{k.name}': trend '{k.trend}' needs data.date_column to be set.")

    for p in cfg.pages:
        for v in p.visuals:
            for name in v.kpis + v.values:
                if name not in kpi_names:
                    raise ConfigError(
                        f"Page '{p.name}': visual '{v.type}' references unknown KPI '{name}'.")
            if v.type == "kpi" and v.value and v.value not in kpi_names:
                raise ConfigError(
                    f"Page '{p.name}': kpi visual references unknown KPI '{v.value}'.")
            if v.type == "gauge":
                if v.value and v.value not in kpi_names:
                    raise ConfigError(
                        f"Page '{p.name}': gauge references unknown KPI '{v.value}'.")
                if not v.value:
                    raise ConfigError(
                        f"Page '{p.name}': gauge visual "
                        f"'{v.title or '(untitled)'}' needs 'value:' naming a KPI.")
                if v.target is None:
                    kpi = next((k for k in cfg.kpis if k.name == v.value), None)
                    if kpi is None or kpi.target is None:
                        raise ConfigError(
                            f"Page '{p.name}': gauge '{v.title or v.value}' has no "
                            f"target. Set 'target:' on KPI '{v.value}' or a numeric "
                            f"'target:' on the visual.")
            if v.type in ("line", "bar", "column", "area") and not v.values:
                raise ConfigError(
                    f"Page '{p.name}': {v.type} visual '{v.title or '(untitled)'}' "
                    f"needs at least one entry in 'values:'.")
            if v.type in ("donut", "pie") and not v.values:
                raise ConfigError(
                    f"Page '{p.name}': {v.type} visual '{v.title or '(untitled)'}' "
                    f"needs exactly one entry in 'values:'.")
            if v.type == "matrix" and not v.rows and not v.values:
                raise ConfigError(
                    f"Page '{p.name}': matrix visual '{v.title or '(untitled)'}' "
                    f"needs 'rows:' and/or 'values:'.")


def page_slug(name: str) -> str:
    return _slug(name)


def visual_slug(title: str, fallback: str) -> str:
    return _slug(title) if title else fallback
