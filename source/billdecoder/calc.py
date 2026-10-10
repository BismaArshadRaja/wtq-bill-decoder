"""Code-side arithmetic: a safe expression evaluator and pre-computed bill stats.

LLMs are unreliable at arithmetic, so the model only *plans* expressions and
this module computes them. Nothing here executes arbitrary code.
"""
from __future__ import annotations

import ast
import operator
from statistics import mean

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "min": min, "max": max, "sum": sum, "abs": abs, "len": len}


def safe_eval(expr: str):
    """Evaluate a pure-arithmetic expression; raises ValueError otherwise."""
    if len(expr) > 500:
        raise ValueError("expression too long")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            right = ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("exponent too large")
            return _BIN[type(node.op)](ev(node.left), right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCS and not node.keywords):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"unsupported syntax: {ast.dump(node)[:80]}")

    return ev(ast.parse(expr.replace("^", "**"), mode="eval"))


def _r(x, n=2):
    return None if x is None else round(x, n)


def bill_stats(level1: dict, facts: dict) -> dict:
    """Common derived numbers, computed once in code for every bill."""
    s: dict = {}
    units = level1.get("units_consumed")
    cur = level1.get("current_bill")
    tc, tt = level1.get("total_charges"), level1.get("total_taxes")
    charges, taxes = level1.get("charges") or [], level1.get("taxes") or []

    s["sum_of_charge_lines"] = _r(sum(c["amount"] for c in charges)) if charges else None
    s["sum_of_tax_lines"] = _r(sum(t["amount"] for t in taxes)) if taxes else None
    tax_total = tt if tt is not None else s["sum_of_tax_lines"]
    if cur:
        s["tax_share_of_current_bill_pct"] = _r(tax_total / cur * 100) if tax_total is not None else None
        if tc is not None:
            s["charges_share_of_current_bill_pct"] = _r(tc / cur * 100)
    if units:
        if cur is not None:
            s["current_bill_per_unit_pkr"] = _r(cur / units)
        energy = sum(c["amount"] for c in charges if c["type"] == "energy")
        if energy:
            s["energy_charges_total"] = _r(energy)
            s["energy_charge_per_unit_pkr"] = _r(energy / units)
    pw, pa = level1.get("payable_within_due_date"), level1.get("payable_after_due_date")
    if pw is not None and pa is not None:
        s["extra_cost_if_paid_late_pkr"] = _r(pa - pw)
    by_type: dict = {}
    for c in charges:
        by_type[c["type"]] = _r(by_type.get(c["type"], 0) + c["amount"])
    s["charges_by_type"] = by_type
    tby: dict = {}
    for t in taxes:
        tby[t["type"]] = _r(tby.get(t["type"], 0) + t["amount"])
    s["taxes_by_type"] = tby

    hist = [h for h in (facts.get("usage_history") or []) if isinstance(h, dict)
            and isinstance(h.get("units"), (int, float))]
    # Does the history list end with the current month? (KE charts show 13 bars incl. current)
    includes_current = False
    if hist:
        from .normalize import to_month
        last_m = to_month(hist[-1].get("month"))
        includes_current = (last_m is not None and last_m == level1.get("bill_month")) or (
            len(hist) >= 13 and hist[-1].get("units") == units)
    prev = hist[:-1] if includes_current else hist
    s["history_includes_current_month"] = includes_current
    s["history_previous_months"] = [f"{h.get('month')}: {h.get('units')}" for h in prev]
    pu = [h["units"] for h in prev]
    if pu:
        s["previous_months_count"] = len(pu)
        s["previous_months_units_average"] = _r(mean(pu))
        s["previous_months_units_total"] = _r(sum(pu))
        hi = max(prev, key=lambda h: h["units"]); lo = min(prev, key=lambda h: h["units"])
        s["previous_months_highest"] = f"{hi.get('month')}: {hi['units']}"
        s["previous_months_lowest"] = f"{lo.get('month')}: {lo['units']}"
        for th in (100, 150, 200, 250, 300, 400, 500):
            over = [f"{h.get('month')} ({h['units']})" for h in prev if h["units"] > th]
            cur_over = units is not None and units > th
            s[f"months_above_{th}_units"] = {
                "previous_months_count": len(over), "previous_months": over,
                "current_month_also_above": cur_over,
                "count_including_current": len(over) + (1 if cur_over else 0)}
        if units is not None:
            s["current_minus_previous_average_units"] = _r(units - mean(pu))
            s["current_vs_previous_average_pct"] = _r((units - mean(pu)) / mean(pu) * 100) if mean(pu) else None
            last = prev[-1]
            s["last_previous_month"] = f"{last.get('month')}: {last['units']}"
            s["current_minus_last_month_units"] = _r(units - last["units"])
    hb = [h.get("bill") for h in prev if isinstance(h.get("bill"), (int, float))]
    if hb:
        s["previous_months_bill_average_pkr"] = _r(mean(hb))
    lps = [x for x in (facts.get("payable_after_due_date") or [])] if isinstance(
        facts.get("payable_after_due_date"), list) else []
    from .normalize import to_number
    tiers = sorted(n for n in (to_number(x) for x in lps) if n is not None)
    if pw is not None and tiers:
        s["late_payment_tiers_extra_pkr"] = [_r(t - pw) for t in tiers]
    lpsur = facts.get("late_payment_surcharge")
    if isinstance(lpsur, list):
        printed = [n for n in (to_number(x) for x in lpsur) if n]
        if printed:
            s["late_payment_surcharges_printed_pkr"] = printed
    for f in ("bill_month", "reading_date", "issue_date", "due_date"):
        s[f] = level1.get(f)
    s["note"] = ("previous_months_* exclude the current billing month. Lists here are complete; "
                 "copy months from them, never add or drop any.")
    return s
