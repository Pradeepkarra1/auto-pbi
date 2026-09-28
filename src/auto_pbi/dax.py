"""DAX measure library.

Every KPI in dashboard.yaml compiles down to one or more DAX measures
through these templates — no hand-written DAX required unless the user
wants a raw override.
"""

from __future__ import annotations

from .config import KpiConfig

FORMAT_STRINGS = {
    "currency": "$#,##0",
    "percent": "0.0%",
    "number": "#,##0.00",
    "decimal": "#,##0.00",
    "integer": "#,##0",
}


def _ref(table: str, column: str) -> str:
    t = f"'{table}'" if " " in table or "-" in table else table
    c = column
    return f"{t}[{c}]"


def _agg_fn(aggregation: str) -> str:
    return {
        "sum": "SUM", "avg": "AVERAGE", "min": "MIN",
        "max": "MAX", "count": "COUNT", "distinct_count": "DISTINCTCOUNT",
    }[aggregation]


def base_measure(kpi: KpiConfig, table: str, rule_dax: dict[str, str]) -> tuple[str, str]:
    """Return (dax_expression, format_string) for the KPI's base measure."""
    if kpi.dax:
        return kpi.dax, FORMAT_STRINGS[kpi.format]
    if kpi.rule:
        return rule_dax[kpi.rule], FORMAT_STRINGS[kpi.format]
    fn = _agg_fn(kpi.aggregation)
    return f"{fn}({_ref(table, kpi.column)})", FORMAT_STRINGS[kpi.format]


def yoy_growth(measure: str, date_table: str = "Date") -> str:
    return (
        "VAR _curr = [{m}]\n"
        "VAR _py = CALCULATE([{m}], SAMEPERIODLASTYEAR('{d}'[Date]))\n"
        "RETURN DIVIDE(_curr - _py, _py)"
    ).format(m=measure, d=date_table)


def mom_growth(measure: str, date_table: str = "Date") -> str:
    return (
        "VAR _curr = [{m}]\n"
        "VAR _pm = CALCULATE([{m}], PREVIOUSMONTH('{d}'[Date]))\n"
        "RETURN DIVIDE(_curr - _pm, _pm)"
    ).format(m=measure, d=date_table)


def qoq_growth(measure: str, date_table: str = "Date") -> str:
    return (
        "VAR _curr = [{m}]\n"
        "VAR _pq = CALCULATE([{m}], PREVIOUSQUARTER('{d}'[Date]))\n"
        "RETURN DIVIDE(_curr - _pq, _pq)"
    ).format(m=measure, d=date_table)


def ytd(measure: str, date_table: str = "Date") -> str:
    return f"CALCULATE([{measure}], DATESYTD('{date_table}'[Date]))"


def vs_target(measure: str) -> str:
    return f"[{measure}] - [{measure} Target]"


def target_achievement(measure: str) -> str:
    return f"DIVIDE([{measure}], [{measure} Target])"


def running_total(measure: str, date_table: str = "Date") -> str:
    """Cumulative total of `measure` along the Date table (for raw `dax:` use)."""
    return (
        "CALCULATE(\n"
        "\t[{m}],\n"
        "\tFILTER(\n"
        "\t\tALL('{d}'[Date]),\n"
        "\t\t'{d}'[Date] <= MAX('{d}'[Date])\n"
        "\t)\n"
        ")"
    ).format(m=measure, d=date_table)


def percent_of_total(measure: str) -> str:
    """Share of `measure` against its grand total (for raw `dax:` use)."""
    return f"DIVIDE([{measure}], CALCULATE([{measure}], ALLSELECTED()))"


def check_balanced(dax: str) -> bool:
    """Cheap sanity check: parentheses/brackets balance."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    in_str = False
    i = 0
    while i < len(dax):
        ch = dax[i]
        if ch == '"':
            # DAX escapes quotes by doubling them
            if in_str and i + 1 < len(dax) and dax[i + 1] == '"':
                i += 2
                continue
            in_str = not in_str
        elif not in_str:
            if ch in pairs:
                stack.append(pairs[ch])
            elif ch in pairs.values():
                if not stack or stack.pop() != ch:
                    return False
        i += 1
    return not stack and not in_str
