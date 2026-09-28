"""PBIR report builder.

Writes `<Project>.Report/`:
    definition.pbir
    definition/version.json
    definition/report.json            (theme binding + report settings)
    definition/pages/pages.json       (page order)
    definition/pages/<page>/page.json
    definition/pages/<page>/visuals/<visual>/visual.json
    StaticResources/RegisteredResources/<Theme>.json

Visual JSON follows the public PBIR visualContainer schema: each visual
binds model fields through query.queryState.<Role>.projections with
queryRef "<Table>.<Field>".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import layout
from .config import DashboardConfig, PageConfig, VisualConfig, page_slug, visual_slug
from .plan import BuildPlan
from .theme import theme_file_stem

VISUAL_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                 "definition/visualContainer/2.9.0/schema.json")
PAGE_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
               "definition/page/2.1.0/schema.json")
PAGES_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definition/pagesMetadata/1.0.0/schema.json")
REPORT_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
                 "definition/report/1.0.0/schema.json")

VISUAL_TYPE_MAP = {
    "kpi": "cardVisual",
    "line": "lineChart",
    "bar": "clusteredBarChart",
    "column": "clusteredColumnChart",
    "area": "areaChart",
    "donut": "donutChart",
    "pie": "pieChart",
    "table": "tableEx",
    "matrix": "pivotTable",
    "slicer": "slicer",
    "gauge": "gauge",
    "textbox": "textbox",
}


def _lit_text(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _measure_proj(table: str, name: str) -> dict:
    return {
        "field": {"Measure": {"Expression": {"SourceRef": {"Entity": table}},
                               "Property": name}},
        "queryRef": f"{table}.{name}",
        "nativeQueryRef": name,
    }


def _column_proj(table: str, column: str) -> dict:
    return {
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}},
                             "Property": column}},
        "queryRef": f"{table}.{column}",
        "nativeQueryRef": column,
    }


class _FieldResolver:
    """Turn config field references into PBIR projections."""

    def __init__(self, plan: BuildPlan):
        self.plan = plan
        self.measure_names = plan.measure_names()
        self.column_names = plan.column_names()

    def _split(self, ref: str, kind: str) -> tuple[str, str]:
        if "." in ref:
            table, col = ref.split(".", 1)
            return table.strip(), col.strip()
        return self.plan.table, ref.strip()

    def projection(self, ref: str) -> dict:
        ref = ref.strip()
        if ref in self.measure_names:
            return _measure_proj(self.plan.table, ref)
        table, col = self._split(ref, "field")
        return _column_proj(table, col)


def _title_vco(title: str) -> dict:
    if not title:
        return {}
    return {"title": [{"properties": {
        "show": {"expr": {"Literal": {"Value": True}}},
        "text": {"expr": {"Literal": {"Value": _lit_text(title)}}},
    }}]}


def _visual_doc(vid: str, pos: dict, visual_type: str, query_state: dict,
                title: str = "", objects: dict | None = None,
                tab_order: int = 0, z: int = 1000) -> dict:
    return {
        "$schema": VISUAL_SCHEMA,
        "name": vid,
        "position": {
            "x": pos["x"], "y": pos["y"], "z": z,
            "width": pos["width"], "height": pos["height"],
            "tabOrder": tab_order,
        },
        "visual": {
            "visualType": visual_type,
            "query": {"queryState": query_state},
            "objects": objects or {},
            "visualContainerObjects": _title_vco(title),
            "drillFilterOtherVisuals": True,
        },
    }


def _textbox_doc(vid: str, pos: dict, text: str, tab_order: int, z: int) -> dict:
    return {
        "$schema": VISUAL_SCHEMA,
        "name": vid,
        "position": {
            "x": pos["x"], "y": pos["y"], "z": z,
            "width": pos["width"], "height": pos["height"],
            "tabOrder": tab_order,
        },
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [
                {"textRuns": [{"value": text,
                               "textStyle": {"fontSize": "20pt", "bold": True}}]}
            ]}}]},
            "visualContainerObjects": {},
        },
    }


def _sort_def(field: dict, direction: str) -> dict:
    return {"sort": [{"field": field["field"], "direction": direction}],
            "isDefaultSort": False}


def build_visual(v: VisualConfig, vid: str, pos: dict, resolver: _FieldResolver,
                 tab_order: int, z: int) -> dict:
    qs: dict = {}
    vtype = VISUAL_TYPE_MAP[v.type]
    title = v.title

    if v.type == "kpi":
        qs["Data"] = {"projections": [resolver.projection(v.value)]}
        title = title or v.value
    elif v.type in ("line", "bar", "column", "area"):
        qs["Category"] = {"projections": [resolver.projection(v.category)]}
        if v.series:
            qs["Series"] = {"projections": [resolver.projection(v.series)]}
        qs["Y"] = {"projections": [resolver.projection(m) for m in v.values]}
    elif v.type in ("donut", "pie"):
        qs["Category"] = {"projections": [resolver.projection(v.category)]}
        qs["Y"] = {"projections": [resolver.projection(v.values[0])]}
    elif v.type == "table":
        qs["Values"] = {"projections": [resolver.projection(c) for c in v.columns]}
    elif v.type == "matrix":
        if v.rows:
            qs["Rows"] = {"projections": [resolver.projection(r) for r in v.rows]}
        if v.category:
            qs["Columns"] = {"projections": [resolver.projection(v.category)]}
        qs["Values"] = {"projections": [resolver.projection(m) for m in v.values]}
    elif v.type == "slicer":
        qs["Values"] = {"projections": [resolver.projection(v.field)]}
    elif v.type == "gauge":
        qs["Y"] = {"projections": [resolver.projection(v.value)]}
        target_measure = _gauge_target(v, resolver)
        qs["TargetValue"] = {"projections": [resolver.projection(target_measure)]}
        title = title or v.value
    elif v.type == "textbox":
        return _textbox_doc(vid, pos, v.text or title, tab_order, z)

    doc = _visual_doc(vid, pos, vtype, qs, title, tab_order=tab_order, z=z)

    # sensible default sorts
    if v.type in ("line", "area") and v.category:
        doc["visual"]["query"]["sortDefinition"] = _sort_def(
            qs["Category"]["projections"][0], "Ascending")
    elif v.type in ("bar", "column") and v.values:
        doc["visual"]["query"]["sortDefinition"] = _sort_def(
            qs["Y"]["projections"][0], "Descending")
    return doc


def _gauge_target(v: VisualConfig, resolver: _FieldResolver) -> str:
    if v.target is not None:
        name = f"{v.title or v.value} Target"
    else:
        name = f"{v.value} Target"
    if name not in resolver.measure_names:
        raise ValueError(
            f"Gauge '{v.title or v.value}': no target measure '{name}'. "
            f"Set a KPI 'target:' or a visual 'target:' number.")
    return name


def _expand_kpi_rows(visuals: list[VisualConfig], cfg: DashboardConfig) -> list[VisualConfig]:
    expanded: list[VisualConfig] = []
    for v in visuals:
        if v.type != "kpi_row":
            expanded.append(v)
            continue
        names = v.kpis or [k.name for k in cfg.kpis if k.show_card]
        for n in names:
            expanded.append(VisualConfig(type="kpi", title=n, value=n))
    return expanded


def _default_pages(cfg: DashboardConfig, plan: BuildPlan) -> list[PageConfig]:
    cards = [k.name for k in cfg.kpis if k.show_card]
    visuals = [VisualConfig(type="kpi_row", kpis=cards)] if cards else []
    if plan.date_table and cards:
        visuals.append(VisualConfig(
            type="line", title=f"{cards[0]} trend",
            category="Date.Month", values=[cards[0]]))
    elif cards:
        first_text = next((c.name for c in plan.columns if c.tmdl_type == "string"), None)
        if first_text:
            visuals.append(VisualConfig(
                type="bar", title=f"{cards[0]} by {first_text}",
                category=f"{plan.table}.{first_text}", values=[cards[0]]))
    if cards:
        cols = [c.name for c in plan.columns[:4]]
        visuals.append(VisualConfig(type="table", title="Detail",
                                    columns=cols + cards[:2]))
    return [PageConfig(name="Overview", visuals=visuals)]


def _glossary_page(plan: BuildPlan) -> PageConfig:
    return PageConfig(name="KPI Glossary", visuals=[
        VisualConfig(type="table", title="KPI Glossary",
                     columns=["KPI Glossary.KPI", "KPI Glossary.Definition",
                              "KPI Glossary.DAX Expression"]),
    ])


def write_report(cfg: DashboardConfig, plan: BuildPlan, out_dir: Path,
                 theme_name: str, theme: dict) -> Path:
    """Write the .Report folder. Returns its path."""
    report = out_dir / f"{plan.project}.Report"
    definition = report / "definition"
    pages_dir = definition / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    res_dir = report / "StaticResources" / "RegisteredResources"
    res_dir.mkdir(parents=True, exist_ok=True)

    def wjson(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")

    # --- pointers & report-level files ---
    wjson(report / "definition.pbir", {
        "version": "1.0",
        "datasetReference": {
            "byPath": {"path": f"../{plan.project}.SemanticModel"},
            "byConnection": None,
        },
    })
    wjson(definition / "version.json", {"version": "2.0.0"})
    wjson(definition / "report.json", {
        "$schema": REPORT_SCHEMA,
        "themeCollection": {
            "customTheme": {
                "name": theme_name,
                "reportVersionAtImport": "5.55",
                "type": "RegisteredResources",
                "packageName": f"RegisteredResources/{theme_file_stem(theme_name)}.json",
            }
        },
        "config": {"version": 5, "defaultDrillFilterOtherVisuals": True},
        "objects": {},
    })
    wjson(res_dir / f"{theme_file_stem(theme_name)}.json", theme)

    # --- pages ---
    pages = list(cfg.pages) or _default_pages(cfg, plan)
    if plan.glossary_rows and cfg.glossary:
        pages.append(_glossary_page(plan))

    resolver = _FieldResolver(plan)
    page_ids: list[str] = []
    seen: set[str] = set()
    for page in pages:
        pid = page_slug(page.name) or "page"
        base, i = pid, 2
        while pid in seen:
            pid = f"{base}_{i}"
            i += 1
        seen.add(pid)
        page_ids.append(pid)

        page_dir = pages_dir / pid
        (page_dir / "visuals").mkdir(parents=True, exist_ok=True)
        wjson(page_dir / "page.json", {
            "$schema": PAGE_SCHEMA,
            "name": pid,
            "displayName": page.name,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
            "visualInteractions": [],
        })

        visuals = _expand_kpi_rows(page.visuals, cfg)
        positions = layout.layout_page(visuals, with_title=True)

        explicit = [False] + [v.x is not None and v.y is not None for v in visuals]
        for i, j in layout.find_overlaps(positions):
            if not (explicit[i] or explicit[j]):
                continue  # auto-layout never overlaps by construction

            def _label(k: int) -> str:
                if k == 0:
                    return "page title"
                v = visuals[k - 1]
                return v.title or v.type

            print(f"warning: page '{page.name}': visuals overlap: "
                  f"'{_label(i)}' with '{_label(j)}' — check x/y/w/h.",
                  file=sys.stderr)

        # auto title textbox
        title_pos = positions[0]
        wjson(page_dir / "visuals" / f"{pid}_title" / "visual.json",
              _textbox_doc(f"{pid}_title", title_pos, page.name, 0, 1000))

        for j, (v, pos) in enumerate(zip(visuals, positions[1:]), start=1):
            vid = visual_slug(v.title or v.value or v.type, f"{pid}_v{j}")
            base_vid, k = vid, 2
            while (page_dir / "visuals" / vid).exists():
                vid = f"{base_vid}_{k}"
                k += 1
            doc = build_visual(v, vid, pos, resolver, tab_order=j, z=1000 + j)
            wjson(page_dir / "visuals" / vid / "visual.json", doc)

    wjson(pages_dir / "pages.json", {
        "$schema": PAGES_SCHEMA,
        "pageOrder": page_ids,
        "activePageName": page_ids[0] if page_ids else "",
    })
    return report
