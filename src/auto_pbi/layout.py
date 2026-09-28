"""Auto-layout engine: flow visuals onto a 1280x720 canvas.

Follows the classic BI detail gradient — KPI cards on top, charts in the
middle, detail tables at the bottom. Any visual can pin an explicit
x/y/w/h in dashboard.yaml to override the flow.
"""

from __future__ import annotations

from .config import VisualConfig

CANVAS_W = 1280
CANVAS_H = 720
MARGIN = 16
GAP = 12
TITLE_H = 64
KPI_H = 148
CHART_H = 330
TABLE_H = 300

# default footprint per visual type: (columns wide, height)
FOOTPRINTS = {
    "kpi": (3, KPI_H),
    "line": (6, CHART_H),
    "bar": (6, CHART_H),
    "column": (6, CHART_H),
    "area": (6, CHART_H),
    "donut": (4, CHART_H),
    "pie": (4, CHART_H),
    "table": (12, TABLE_H),
    "matrix": (6, TABLE_H),
    "slicer": (3, 96),
    "gauge": (4, CHART_H),
    "textbox": (12, 72),
}


def find_overlaps(positions: list[dict]) -> list[tuple[int, int]]:
    """Return index pairs (into `positions`) whose rectangles overlap."""
    pairs: list[tuple[int, int]] = []
    rects = [(p["x"], p["y"], p["x"] + p["width"], p["y"] + p["height"])
             for p in positions]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            ax1, ay1, ax2, ay2 = rects[i]
            bx1, by1, bx2, by2 = rects[j]
            if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2:
                pairs.append((i, j))
    return pairs


def layout_page(visuals: list[VisualConfig], with_title: bool = True) -> list[dict]:
    """Return [{x,y,width,height}] positions aligned with `visuals` order."""
    col_w = (CANVAS_W - 2 * MARGIN - 11 * GAP) / 12
    positions: list[dict] = []

    y = MARGIN
    if with_title:
        positions.append({"x": MARGIN, "y": y, "width": CANVAS_W - 2 * MARGIN, "height": TITLE_H})
        y += TITLE_H + GAP

    x = MARGIN
    row_h = 0
    pending: list[tuple[int, VisualConfig, float, float]] = []

    def flush_row():
        nonlocal y, x, row_h, pending
        for idx, _v, w, h in pending:
            positions[idx]["y"] = y
            positions[idx]["height"] = h
        if pending:
            y += row_h + GAP
        x = MARGIN
        row_h = 0
        pending = []

    # reserve slots: title occupies index 0 when present
    for v in visuals:
        positions.append({})

    start = 1 if with_title else 0
    for i, v in enumerate(visuals, start=start):
        if v.x is not None and v.y is not None:
            flush_row()
            positions[i] = {
                "x": v.x, "y": v.y,
                "width": v.w or 400, "height": v.h or 300,
            }
            continue
        cols, h = FOOTPRINTS.get(v.type, (6, CHART_H))
        w = cols * col_w + (cols - 1) * GAP
        if v.type == "kpi_row":
            # kpi_row expands into N cards handled by the caller; reserve full row
            cols, h = 12, KPI_H
            w = CANVAS_W - 2 * MARGIN
        if x + w > CANVAS_W - MARGIN + 1 and pending:
            flush_row()
        positions[i] = {"x": round(x, 1), "y": 0, "width": round(w, 1), "height": h}
        pending.append((i, v, w, h))
        row_h = max(row_h, h)
        x += w + GAP
    flush_row()
    return positions
