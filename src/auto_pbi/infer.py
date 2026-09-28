"""Infer a table schema from the clean source file.

Supports CSV today (the overwhelmingly common "clean data" handoff);
Parquet support hooks in via pandas when available. The inferred schema
drives the TMDL table definition and the Power Query M `Changed Type` step.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%dT%H:%M:%S",
)


@dataclass
class ColumnInfo:
    name: str
    tmdl_type: str        # string | int64 | double | dateTime | boolean
    m_type: str           # M type literal for Table.TransformColumnTypes
    date_only: bool = False


def _looks_like_date(value: str) -> tuple[bool, bool]:
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return True, dt.time() == datetime.min.time()
        except ValueError:
            continue
    return False, False


def _infer_column(values: list[str]) -> tuple[str, str, bool]:
    seen_int = seen_float = seen_bool = seen_date = seen_str = False
    date_only = True
    for v in values:
        v = (v or "").strip()
        if v == "":
            continue
        low = v.lower()
        if low in ("true", "false", "yes", "no", "y", "n"):
            # word booleans only: bare "1"/"0" are far more useful as integers
            seen_bool = True
            continue
        try:
            int(v.replace(",", ""))
            seen_int = True
            continue
        except ValueError:
            pass
        try:
            float(v.replace(",", ""))
            seen_float = True
            continue
        except ValueError:
            pass
        is_date, only = _looks_like_date(v)
        if is_date:
            seen_date = True
            date_only = date_only and only
            continue
        seen_str = True
    if seen_str:
        return "string", "type text", False
    if seen_date and not (seen_int or seen_float or seen_bool):
        return "dateTime", "type date" if date_only else "type datetime", date_only
    if seen_bool and not (seen_int or seen_float):
        return "boolean", "type logical", False
    if seen_float:
        return "double", "Double.Type", False
    if seen_int:
        return "int64", "Int64.Type", False
    return "string", "type text", False


def infer_csv(path: Path, sample_rows: int = 2000) -> list[ColumnInfo]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        headers = [h.strip() for h in reader.fieldnames]
        lowered = [h.lower() for h in headers]
        dupes = sorted({h for h in headers if lowered.count(h.lower()) > 1})
        if dupes:
            raise ValueError(
                f"Duplicate column names in {path}: {dupes}. "
                f"Column names must be unique (case-insensitive).")
        if any(h == "" for h in headers):
            raise ValueError(f"Empty column name in header row of {path}.")
        buckets: dict[str, list[str]] = {h: [] for h in headers}
        for i, row in enumerate(reader):
            if i >= sample_rows:
                break
            for h in headers:
                buckets[h].append(row.get(h, "") or "")
    cols = []
    for h in headers:
        tmdl_type, m_type, date_only = _infer_column(buckets[h])
        cols.append(ColumnInfo(name=h, tmdl_type=tmdl_type, m_type=m_type, date_only=date_only))
    return cols


def quality_warnings(path: Path, columns: list[ColumnInfo],
                     sample_rows: int = 2000) -> list[str]:
    """Non-fatal data-quality observations worth surfacing to the user."""
    warnings: list[str] = []
    suffix = path.suffix.lower()
    if suffix not in (".csv",):
        return warnings
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [(h or "").strip() for h in (reader.fieldnames or [])]
        n_rows = 0
        empty: dict[str, int] = {h: 0 for h in headers}
        for i, row in enumerate(reader):
            if i >= sample_rows:
                break
            n_rows += 1
            for h in headers:
                if not (row.get(h, "") or "").strip():
                    empty[h] += 1
    if n_rows == 0:
        warnings.append("data file has a header row but no data rows.")
    for h in headers:
        if n_rows and empty[h] == n_rows:
            warnings.append(f"column '{h}' is empty in every sampled row.")
        elif n_rows and empty[h] / n_rows > 0.5:
            warnings.append(
                f"column '{h}' is blank in {empty[h]}/{n_rows} sampled rows.")
    return warnings


def infer_schema(path: Path) -> list[ColumnInfo]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return infer_csv(path)
    if suffix in (".parquet", ".pq"):
        try:
            import pandas as pd  # type: ignore
        except ImportError as e:
            raise ValueError("Parquet sources need pandas+pyarrow: pip install pandas pyarrow") from e
        df = pd.read_parquet(path)
        cols = []
        for name in df.columns:
            kind = str(df[name].dtype)
            if kind.startswith("int"):
                cols.append(ColumnInfo(str(name), "int64", "Int64.Type"))
            elif kind.startswith("float"):
                cols.append(ColumnInfo(str(name), "double", "Double.Type"))
            elif kind.startswith("bool"):
                cols.append(ColumnInfo(str(name), "boolean", "type logical"))
            elif "datetime" in kind or "date" in kind:
                cols.append(ColumnInfo(str(name), "dateTime", "type datetime"))
            else:
                cols.append(ColumnInfo(str(name), "string", "type text"))
        return cols
    raise ValueError(f"Unsupported data source '{suffix}'. Use .csv or .parquet.")
