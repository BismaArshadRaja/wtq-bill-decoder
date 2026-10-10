"""Configuration loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

ALLOWED_MODELS = {
    "anthropic": {"claude-haiku-4-5"},
    "google": {"gemini-3.5-flash-lite", "gemini-3.1-flash-lite"},
    "openai": {"gpt-4.1-mini", "gpt-5-mini"},
    "mock": {"mock"},  # offline pipeline test only, no API calls
}


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str
    max_retries: int
    min_seconds_between_calls: float
    cache_dir: str


def load_settings() -> Settings:
    provider = os.getenv("MODEL_PROVIDER", "google").strip().lower()
    model = os.getenv("MODEL_NAME", "gemini-3.5-flash-lite").strip()
    if provider not in ALLOWED_MODELS:
        raise SystemExit(f"MODEL_PROVIDER must be one of {sorted(ALLOWED_MODELS)}")
    if model not in ALLOWED_MODELS[provider]:
        raise SystemExit(
            f"MODEL_NAME '{model}' is not an allowed model for {provider}. "
            f"Allowed: {sorted(ALLOWED_MODELS[provider])}"
        )
    api_key = os.getenv("API_KEY", "").strip()
    if provider != "mock" and (not api_key or api_key == "your-api-key-here"):
        raise SystemExit("API_KEY is missing. Copy .env.example to .env and set it.")
    return Settings(
        provider=provider,
        model=model,
        api_key=api_key,
        max_retries=int(os.getenv("MAX_RETRIES", "5")),
        # Gemini free tier = 15 requests/min, so 4.5 s keeps us safely below it.
        min_seconds_between_calls=float(os.getenv("MIN_SECONDS_BETWEEN_CALLS", "4.5")),
        cache_dir=os.getenv("CACHE_DIR", ".cache"),
    )
