"""Level 1: read a bill image into structured facts, then into the exact schema.

Flow per bill:
  1. Vision call with a provider-specific prompt -> rich "facts" JSON
     (Level 1 fields + line labels, usage history, late-payment amounts...).
  2. Deterministic normalisation (normalize.py) -> exact Level 1 schema.
  3. Arithmetic cross-checks; if anything looks off, one focused re-read.
The facts are cached on disk and reused by Level 2, so each bill is read once.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import prompts
from .llm import LLMClient, load_image_views
from .normalize import consistency_issues, normalize_level1, provider_from_bill_id

log = logging.getLogger(__name__)


class Extractor:
    def __init__(self, llm: LLMClient, cache_dir: str):
        self.llm = llm
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)

    def facts(self, bill_id: str, image_path: Path) -> dict:
        """Return cached facts for a bill, extracting them if needed."""
        tag = f"{self.llm.s.provider}_{self.llm.s.model}".replace("/", "_")
        cache_file = self.cache / f"{bill_id}.{tag}.facts.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        provider = provider_from_bill_id(bill_id) or "Pakistani"
        image = load_image_views(image_path)
        prompt = prompts.EXTRACT_PROMPT.format(
            provider=provider, layout_hints=prompts.LAYOUT_HINTS.get(provider, ""))
        raw = self.llm.json_call(prompts.EXTRACT_SYSTEM, prompt, image)
        if not isinstance(raw, dict):
            raw = {}

        issues = consistency_issues(normalize_level1(raw, bill_id))
        if issues and self.llm.s.provider != "mock":
            log.info("%s: re-checking (%s)", bill_id, "; ".join(issues))
            try:
                fixed = self.llm.json_call(
                    prompts.EXTRACT_SYSTEM,
                    prompts.VERIFY_PROMPT.format(
                        issues="\n".join(f"- {i}" for i in issues),
                        previous=json.dumps(raw, ensure_ascii=False)),
                    image)
                if isinstance(fixed, dict) and fixed:
                    # keep the re-read only if it does not make the checks worse
                    if len(consistency_issues(normalize_level1(fixed, bill_id))) <= len(issues):
                        raw = {**raw, **fixed}
            except RuntimeError as e:
                log.warning("%s: verify pass failed, keeping first read: %s", bill_id, e)

        raw["provider"] = provider
        cache_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return raw

    def level1(self, bill_id: str, image_path: Path) -> dict:
        return normalize_level1(self.facts(bill_id, image_path), bill_id)
