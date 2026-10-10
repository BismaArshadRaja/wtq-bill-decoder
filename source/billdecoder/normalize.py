"""Deterministic post-processing of model output into the exact Level 1 schema.

The LLM reads the bill; this module enforces the format rules in code so the
JSON is always valid: numbers not strings, CR -> negative, ISO dates, allowed
type enums, zero/blank lines dropped, every field present.
"""
from __future__ import annotations

import re
from datetime import datetime

from dateutil import parser as dateparser

CHARGE_TYPES = {"energy", "fixed", "fpa", "quarterly_adjustment", "surcharge",
                "meter_rent", "subsidy", "other"}
TAX_TYPES = {"gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax"}

LEVEL1_FIELDS = [
    "provider", "tariff", "sanctioned_load_kw", "bill_month", "reading_date",
    "issue_date", "due_date", "previous_reading", "current_reading",
    "units_consumed", "charges", "total_charges", "taxes", "total_taxes",
    "current_bill", "arrears", "payable_within_due_date", "payable_after_due_date",
]

PROVIDER_FROM_PREFIX = {"KESC": "KE", "KE": "KE", "LESCO": "LESCO", "IESCO": "IESCO"}


def provider_from_bill_id(bill_id: str) -> str | None:
    prefix = bill_id.split("_")[0].upper()
    return PROVIDER_FROM_PREFIX.get(prefix)


def to_number(v):
    """'Rs. 19,964' -> 19964 ; '38209CR' -> -38209 ; '(12)' -> -12 ; junk -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else float(v)
    s = str(v).strip()
    if not s or s.lower() in {"null", "none", "n/a", "na", "-", "--"}:
        return None
    neg = False
    if re.search(r"\bCR\b|CR$|Cr$", s):
        neg = True
    if s.startswith("(") and s.endswith(")"):
        neg = True
    s2 = re.sub(r"(?i)rs\.?|pkr|kwh|kw|units?|cr", "", s)
    s2 = s2.replace(",", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s2)
    if not m:
        return None
    num = float(m.group(0))
    if neg and num > 0:
        num = -num
    return int(num) if num.is_integer() else num


def to_iso_date(v) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    try:
        # Pakistani bills are day-first (03-Apr-26, 21/04/2026)
        d = dateparser.parse(s, dayfirst=True, default=datetime(2000, 1, 1))
        return d.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def to_month(v) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s[:7]
    # "Apr-26", "MAR 26", "APR 2026"
    m = re.fullmatch(r"([A-Za-z]{3,9})[\s\-/']*(\d{2}|\d{4})", s)
    if m:
        yr = m.group(2)
        yr = "20" + yr if len(yr) == 2 else yr
        try:
            d = dateparser.parse(f"1 {m.group(1)} {yr}")
            return d.strftime("%Y-%m")
        except (ValueError, OverflowError):
            return None
    try:
        return dateparser.parse(s, default=dateparser.parse("2000-01-01")).strftime("%Y-%m")
    except (ValueError, OverflowError):
        return None


def _clean_items(items, allowed: set[str], fallback: str, negative_types=()):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        amt = to_number(it.get("amount"))
        if amt is None or amt == 0:
            continue  # skip blank lines and lines printed as 0
        typ = str(it.get("type", "")).strip().lower()
        if typ not in allowed:
            typ = fallback
        if typ in negative_types and amt > 0:
            amt = -amt  # subsidies are deductions
        out.append({"type": typ, "amount": amt})
    return out


def normalize_level1(raw: dict, bill_id: str) -> dict:
    raw = raw or {}
    out = {
        "provider": provider_from_bill_id(bill_id) or raw.get("provider"),
        "tariff": (str(raw["tariff"]).strip() or None) if raw.get("tariff") else None,
        "sanctioned_load_kw": to_number(raw.get("sanctioned_load_kw")),
        "bill_month": to_month(raw.get("bill_month")),
        "reading_date": to_iso_date(raw.get("reading_date")),
        "issue_date": to_iso_date(raw.get("issue_date")),
        "due_date": to_iso_date(raw.get("due_date")),
        "previous_reading": to_number(raw.get("previous_reading")),
        "current_reading": to_number(raw.get("current_reading")),
        "units_consumed": to_number(raw.get("units_consumed")),
        "charges": _clean_items(raw.get("charges"), CHARGE_TYPES, "other", ("subsidy",)),
        "total_charges": to_number(raw.get("total_charges")),
        "taxes": _clean_items(raw.get("taxes"), TAX_TYPES, "other_tax"),
        "total_taxes": to_number(raw.get("total_taxes")),
        "current_bill": to_number(raw.get("current_bill")),
        "arrears": to_number(raw.get("arrears")),
        "payable_within_due_date": to_number(raw.get("payable_within_due_date")),
        "payable_after_due_date": None,
    }
    # If several late-payment amounts are given, use the highest.
    pad = raw.get("payable_after_due_date")
    if isinstance(pad, list):
        nums = [n for n in (to_number(x) for x in pad) if n is not None]
        out["payable_after_due_date"] = max(nums) if nums else None
    else:
        out["payable_after_due_date"] = to_number(pad)
    return {k: out[k] for k in LEVEL1_FIELDS}


def consistency_issues(j: dict) -> list[str]:
    """Arithmetic cross-checks used to decide whether to re-read the bill.

    These never overwrite values (the rules say extract as printed); they only
    trigger a focused second look by the model.
    """
    issues = []

    def close(a, b, tol=2.0):
        return a is not None and b is not None and abs(a - b) <= tol

    pr, cr, u = j["previous_reading"], j["current_reading"], j["units_consumed"]
    if pr is not None and cr is not None and u is not None and cr - pr > 0 and not close(cr - pr, u, 1):
        issues.append(f"current_reading - previous_reading = {cr - pr} but units_consumed = {u} "
                      "(may be legit if a meter multiplier applies; re-check digits)")
    if not j["charges"] and j["total_charges"]:
        issues.append(f"charges list is empty but a charges total of {j['total_charges']} is "
                      "printed: list every individual line of the charges section")
    if j["charges"] and j["total_charges"] is not None:
        s = round(sum(c["amount"] for c in j["charges"]), 2)
        if not close(s, j["total_charges"]):
            issues.append(f"sum of charges = {s} but total_charges = {j['total_charges']}")
    if j["taxes"] and j["total_taxes"] is not None:
        s = round(sum(t["amount"] for t in j["taxes"]), 2)
        if not close(s, j["total_taxes"]):
            issues.append(f"sum of taxes = {s} but total_taxes = {j['total_taxes']}")
    cb, ar, pw = j["current_bill"], j["arrears"], j["payable_within_due_date"]
    if cb is not None and pw is not None and not close(cb + (ar or 0), pw, 2):
        issues.append(f"current_bill {cb} + arrears {ar} != payable_within_due_date {pw}; check "
                      "for missed lines such as installment, deferred amount or FPA added below "
                      "the current bill (fine if the bill really prints these values)")
    if j["payable_within_due_date"] is not None and j["payable_after_due_date"] is not None:
        if j["payable_after_due_date"] < j["payable_within_due_date"]:
            issues.append("payable_after_due_date is smaller than payable_within_due_date")
    for f in ("due_date", "issue_date"):
        if j[f] and j["reading_date"] and j[f] < j["reading_date"]:
            issues.append(f"{f} {j[f]} is before reading_date {j['reading_date']}")
    return issues
