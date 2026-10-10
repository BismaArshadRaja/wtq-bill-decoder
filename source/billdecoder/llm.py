"""Thin, provider-agnostic wrapper: (prompt + optional image) -> parsed JSON.

Supports only the competition's allowed models (see config.ALLOWED_MODELS).
Handles retries with exponential backoff, simple client-side rate limiting,
and robust JSON parsing of the model's reply.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from pathlib import Path

from PIL import Image, ImageOps

from .config import Settings

log = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 2400  # px; enough detail for small bill print, keeps tokens sane


def _to_jpeg(img: Image.Image) -> bytes:
    img = img.copy()
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _open(path: str | Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def load_image_jpeg(path: str | Path) -> bytes:
    """Load an image, fix EXIF rotation, downscale, return JPEG bytes."""
    return _to_jpeg(_open(path))


def load_image_views(path: str | Path) -> list[bytes]:
    """Full bill + zoomed top and bottom halves (55% each, overlapping).

    Bills print line items in tiny type; the zoomed halves give the model
    roughly twice the effective resolution on every line.
    """
    img = _open(path)
    w, h = img.size
    if h >= w:  # portrait: split top / bottom
        top, bottom = img.crop((0, 0, w, int(h * 0.55))), img.crop((0, int(h * 0.45), w, h))
    else:  # landscape: split left / right
        top, bottom = img.crop((0, 0, int(w * 0.55), h)), img.crop((int(w * 0.45), 0, w, h))
    return [_to_jpeg(img), _to_jpeg(top), _to_jpeg(bottom)]


def parse_json_reply(text: str):
    """Extract the first JSON object/array from a model reply."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError(f"No JSON found in model reply: {text[:200]}")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start : end + 1])


class LLMClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._last_call = 0.0
        if settings.provider == "google":
            from google import genai

            self._client = genai.Client(api_key=settings.api_key)
        elif settings.provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=settings.api_key)
        elif settings.provider == "openai":
            import openai

            self._client = openai.OpenAI(api_key=settings.api_key)
        else:
            self._client = None

    # ---- public ---------------------------------------------------------
    def json_call(self, system: str, prompt: str, image: bytes | list[bytes] | None = None):
        """Call the model and return parsed JSON, retrying on any failure."""
        delay = 5.0
        last_err: Exception | None = None
        for attempt in range(1, self.s.max_retries + 1):
            try:
                self._throttle()
                images = image if isinstance(image, list) else ([image] if image else [])
                text = self._raw_call(system, prompt, images)
                return parse_json_reply(text)
            except Exception as e:  # network, rate limit, bad JSON...
                last_err = e
                log.warning("LLM call failed (attempt %d/%d): %s", attempt, self.s.max_retries, e)
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise RuntimeError(f"LLM call failed after retries: {last_err}")

    # ---- internals ------------------------------------------------------
    def _throttle(self):
        wait = self.s.min_seconds_between_calls - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _raw_call(self, system: str, prompt: str, images: list[bytes]) -> str:
        p = self.s.provider
        if p == "google":
            from google.genai import types

            parts = [types.Part.from_bytes(data=im, mime_type="image/jpeg") for im in images]
            parts.append(prompt)
            resp = self._client.models.generate_content(
                model=self.s.model,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                    response_mime_type="application/json",
                    media_resolution=(types.MediaResolution.MEDIA_RESOLUTION_HIGH
                                      if images else None),
                ),
            )
            return resp.text

        if p == "anthropic":
            content = [{
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                           "data": base64.b64encode(im).decode()},
            } for im in images]
            content.append({"type": "text", "text": prompt})
            resp = self._client.messages.create(
                model=self.s.model, max_tokens=8000, temperature=0,
                system=system, messages=[{"role": "user", "content": content}],
            )
            return "".join(b.text for b in resp.content if b.type == "text")

        if p == "openai":
            content = [{"type": "text", "text": prompt}]
            for im in images:
                url = "data:image/jpeg;base64," + base64.b64encode(im).decode()
                content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
            kwargs = dict(
                model=self.s.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": content}],
                response_format={"type": "json_object"},
            )
            if not self.s.model.startswith("gpt-5"):  # gpt-5 models reject temperature
                kwargs["temperature"] = 0
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content

        # mock: offline smoke test of the pipeline
        return "{}"
