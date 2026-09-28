"""Theme engine — generates a Power BI theme JSON per build.

A cohesive theme is what makes generated dashboards look designed rather
than default. Themes live in
`<Report>/StaticResources/RegisteredResources/<Theme>.json` and are
referenced from the PBIR report.json `themeCollection`.
"""

from __future__ import annotations

import re
from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "midnight": {
        "background": "#0F1419",
        "foreground": "#F5F7FA",
        "tableAccent": "#1B6CA8",
        "palette": ["#1B6CA8", "#5BC0EB", "#9BC53D", "#E55934",
                    "#FA7921", "#FDE74C", "#7D5BA6", "#35A7FF"],
    },
    "corporate": {
        "background": "#FFFFFF",
        "foreground": "#252423",
        "tableAccent": "#118DFF",
        "palette": ["#118DFF", "#12239E", "#E66C37", "#6B007B",
                    "#E044A7", "#744EC2", "#D9B300", "#D9B300"],
    },
    "forest": {
        "background": "#F7F9F5",
        "foreground": "#1E2A1E",
        "tableAccent": "#2D6A4F",
        "palette": ["#2D6A4F", "#40916C", "#95D5B2", "#D8F3DC",
                    "#F4A259", "#BC6C25", "#606C38", "#283618"],
    },
    "sunset": {
        "background": "#1A1210",
        "foreground": "#FFF8F0",
        "tableAccent": "#E55934",
        "palette": ["#E55934", "#FA7921", "#FDE74C", "#9BC53D",
                    "#5BC0EB", "#1B6CA8", "#7D5BA6", "#35A7FF"],
    },
}


def theme_file_stem(name: str) -> str:
    """Filesystem-safe stem for the theme JSON file (display name keeps spaces)."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return stem or "Theme"


def resolve_theme(spec: Any, project_name: str) -> tuple[str, dict]:
    """Return (theme_name, theme_json_dict) for a theme spec.

    spec may be a preset name, or a dict like:
        theme:
          name: My Theme
          palette: ["#123456", ...]     # or dataColors: [...] / colors: [...]
          background: "#FFFFFF"
          foreground: "#111111"
    """
    if isinstance(spec, dict):
        preset = PRESETS.get(str(spec.get("preset", "midnight")).lower(), PRESETS["midnight"])
        merged = dict(preset)
        for k, v in spec.items():
            if k in merged:
                merged[k] = v
        # common aliases for the palette, so either spelling works
        for alias in ("dataColors", "colors", "data_colors"):
            if spec.get(alias):
                merged["palette"] = list(spec[alias])
                break
        name = str(spec.get("name") or f"{project_name} Theme")
    else:
        merged = PRESETS.get(str(spec).lower(), PRESETS["midnight"])
        name = f"AutoPBI {str(spec).capitalize() if spec else 'Midnight'}"

    theme = {
        "name": name,
        "dataColors": merged["palette"],
        "background": merged["background"],
        "foreground": merged["foreground"],
        "tableAccent": merged["tableAccent"],
        "visualStyles": {
            "*": {
                "*": {
                    "fontFamily": [{"fontFamily": {"expr": {"Literal": {"Value": "'Segoe UI'"}}}}]
                }
            },
            "cardVisual": {
                "*": {
                    "value": [{
                        "fontSize": {"expr": {"Literal": {"Value": "30D"}}},
                        "fontColor": {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": 0, "Percent": 0}}}}},
                    }],
                    "categoryLabel": [{
                        "fontSize": {"expr": {"Literal": {"Value": "12D"}}},
                    }],
                }
            },
            "tableEx": {
                "*": {
                    "grid": [{
                        "gridVertical": {"expr": {"Literal": {"Value": "true"}}},
                        "gridHorizontal": {"expr": {"Literal": {"Value": "true"}}},
                    }],
                }
            },
        },
    }
    return name, theme
