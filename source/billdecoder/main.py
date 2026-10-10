"""Command-line entry point.

  python -m billdecoder.main run  --bills ../test/bills --level1 ../test/csv/level1.csv \
                                  --level2 ../test/csv/level2.csv --out ../output
  python -m billdecoder.main demo --bill ../train/bills/KESC_0008.png \
                                  --question "How much of my bill is taxes?"
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import OrderedDict
from pathlib import Path

from .answer import FALLBACK, answer_bill
from .config import load_settings
from .extract import Extractor
from .llm import LLMClient, load_image_jpeg
from .normalize import normalize_level1

log = logging.getLogger("billdecoder")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def find_image(bills_dir: Path, bill_id: str) -> Path | None:
    for ext in IMAGE_EXTS:
        for cand in (bills_dir / f"{bill_id}{ext}", bills_dir / f"{bill_id}{ext.upper()}"):
            if cand.exists():
                return cand
    return None


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)


def compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def cmd_run(args) -> int:
    settings = load_settings()
    llm = LLMClient(settings)
    ext = Extractor(llm, settings.cache_dir)
    bills_dir, out_dir = Path(args.bills), Path(args.out)

    # ---------- Level 1 ----------
    l1_fields, l1_rows = read_csv(Path(args.level1))
    level1_by_bill: dict[str, dict] = {}
    for i, row in enumerate(l1_rows, 1):
        bid = row["bill_id"].strip()
        img = find_image(bills_dir, bid)
        log.info("[L1 %d/%d] %s", i, len(l1_rows), bid)
        try:
            if img is None:
                raise FileNotFoundError(f"no image for {bid} in {bills_dir}")
            j = ext.level1(bid, img)
        except Exception as e:
            log.error("%s: extraction failed (%s); writing nulls", bid, e)
            j = normalize_level1({}, bid)
        level1_by_bill[bid] = j
        row["json"] = compact(j)
    write_csv(out_dir / "level1.csv", l1_fields, l1_rows)
    log.info("wrote %s", out_dir / "level1.csv")

    if not args.level2:
        return 0

    # ---------- Level 2 ----------
    l2_fields, l2_rows = read_csv(Path(args.level2))
    grouped: "OrderedDict[str, dict[str, str]]" = OrderedDict()
    for row in l2_rows:
        grouped.setdefault(row["bill_id"].strip(), {})[row["question_id"].strip()] = row["question"]

    answers: dict[tuple[str, str], str] = {}
    for i, (bid, questions) in enumerate(grouped.items(), 1):
        log.info("[L2 %d/%d] %s (%d questions)", i, len(grouped), bid, len(questions))
        img = find_image(bills_dir, bid)
        try:
            if img is None:
                raise FileNotFoundError(f"no image for {bid}")
            facts = ext.facts(bid, img)
            l1 = level1_by_bill.get(bid) or normalize_level1(facts, bid)
            got = answer_bill(llm, facts, l1, load_image_jpeg(img), questions)
        except Exception as e:
            log.error("%s: answering failed (%s)", bid, e)
            got = {q: FALLBACK for q in questions}
        for qid, a in got.items():
            answers[(bid, qid)] = a

    for row in l2_rows:
        row["answer"] = answers.get((row["bill_id"].strip(), row["question_id"].strip()), FALLBACK)
    write_csv(out_dir / "level2.csv", l2_fields, l2_rows)
    log.info("wrote %s", out_dir / "level2.csv")
    return 0


def cmd_demo(args) -> int:
    settings = load_settings()
    llm = LLMClient(settings)
    ext = Extractor(llm, settings.cache_dir)
    img = Path(args.bill)
    bid = img.stem
    facts = ext.facts(bid, img)
    l1 = normalize_level1(facts, bid)
    print(f"\n=== Level 1: {bid} ===")
    print(json.dumps(l1, ensure_ascii=False, indent=2))
    if args.question:
        qs = {f"Q{i}": q for i, q in enumerate(args.question, 1)}
        ans = answer_bill(llm, facts, l1, load_image_jpeg(img), qs)
        print(f"\n=== Level 2: {bid} ===")
        for qid, q in qs.items():
            print(f"\n{qid}. {q}\n-> {ans[qid]}")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    p = argparse.ArgumentParser(prog="billdecoder", description="Utility Bill Decoder")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fill level1.csv / level2.csv for a folder of bills")
    r.add_argument("--bills", required=True, help="folder with bill images")
    r.add_argument("--level1", required=True, help="level1.csv template")
    r.add_argument("--level2", help="level2.csv template (optional)")
    r.add_argument("--out", default="output", help="output folder (default: output)")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("demo", help="decode one bill and answer questions")
    d.add_argument("--bill", required=True, help="path to a bill image")
    d.add_argument("--question", action="append", help="question (repeatable)")
    d.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
