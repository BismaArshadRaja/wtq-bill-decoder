"""Level 2: answer customer questions about a bill.

Plan -> compute -> write, all 12 questions of a bill per call:
  1. PLAN  (text-only call): the model lists the arithmetic each question needs.
  2. COMPUTE (code): calc.safe_eval runs every expression; calc.bill_stats adds
     common derived numbers. The model never does arithmetic itself.
  3. WRITE (vision call): the model writes plain-English answers from the bill
     data, the image and the code-verified numbers.
"""
from __future__ import annotations

import json
import logging

from . import prompts
from .calc import bill_stats, safe_eval
from .llm import LLMClient

log = logging.getLogger(__name__)

FALLBACK = ("Sorry, I could not produce a reliable answer from this bill. The needed "
            "information may not be printed or readable on the bill.")


def _strip_labels(facts: dict) -> dict:
    """Facts shown to the answer model (drop extraction bookkeeping)."""
    return {k: v for k, v in facts.items() if k not in {"unreadable_or_hidden"}}


def answer_bill(llm: LLMClient, facts: dict, level1: dict, image: bytes | None,
                questions: dict[str, str]) -> dict[str, str]:
    """questions: {"Q1": "text", ...} -> {"Q1": "answer", ...} (never empty)."""
    facts_json = json.dumps({"level1": level1, "details": _strip_labels(facts)},
                            ensure_ascii=False)
    stats_json = json.dumps(bill_stats(level1, facts), ensure_ascii=False)
    q_text = "\n".join(f"{qid}: {q}" for qid, q in questions.items())

    # 1. PLAN
    results: dict = {}
    try:
        plan = llm.json_call(prompts.PLAN_SYSTEM,
                             prompts.PLAN_PROMPT.format(facts=facts_json, stats=stats_json,
                                                        questions=q_text))
    except RuntimeError as e:
        log.warning("plan call failed: %s", e)
        plan = {}

    # 2. COMPUTE
    for qid in questions:
        p = plan.get(qid) if isinstance(plan, dict) else None
        if not isinstance(p, dict):
            continue
        entry = {"calculations": [], "missing": p.get("missing") or [],
                 "interpretations": p.get("interpretations") or []}
        for c in p.get("calculations") or []:
            if not isinstance(c, dict) or not c.get("expr"):
                continue
            try:
                val = safe_eval(str(c["expr"]))
                if isinstance(val, float):
                    val = round(val, 2)
                entry["calculations"].append(
                    {"name": c.get("name", ""), "expr": c["expr"], "result": val})
            except Exception as e:  # bad expression -> tell the writer it failed
                entry["calculations"].append(
                    {"name": c.get("name", ""), "expr": c["expr"], "result": f"error: {e}"})
        results[qid] = entry

    # 3. WRITE
    answers: dict = {}
    try:
        answers = llm.json_call(
            prompts.ANSWER_SYSTEM,
            prompts.ANSWER_PROMPT.format(facts=facts_json, stats=stats_json,
                                         results=json.dumps(results, ensure_ascii=False),
                                         questions=q_text),
            image)
    except RuntimeError as e:
        log.warning("answer call failed: %s", e)

    out = {}
    for qid in questions:
        a = answers.get(qid) if isinstance(answers, dict) else None
        out[qid] = " ".join(str(a).split()) if a and str(a).strip() else FALLBACK
    return out
