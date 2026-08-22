"""Configuration and decision thresholds for PatentLoop."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field


MAX_ITERATIONS = 5
NOVELTY_GATE = 55
OVERLAP_GATE = 45
SATURATION_COSINE = 0.88
SATURATION_OVERLAP = 55
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY"))
    openai_base_url: str = field(default_factory=lambda: os.environ.get(
        "OPENAI_BASE_URL", "https://api.openai.com/v1"
    ))
    model: str = field(default_factory=lambda: os.environ.get("PATENTLOOP_MODEL", DEFAULT_MODEL))
    embedding_model: str = field(default_factory=lambda: os.environ.get(
        "PATENTLOOP_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
    ))
    model_cache: str | None = field(
        default_factory=lambda: os.environ.get("PATENTLOOP_MODEL_CACHE")
    )
    uspto_api_key: str | None = field(default_factory=lambda: os.environ.get("USPTO_ODP_API_KEY"))
    epo_key: str | None = field(default_factory=lambda: os.environ.get("EPO_OPS_KEY"))
    epo_secret: str | None = field(default_factory=lambda: os.environ.get("EPO_OPS_SECRET"))
    semantic_scholar_key: str | None = field(default_factory=lambda: os.environ.get("S2_API_KEY"))
    github_token: str | None = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN"))
    devin_api_key: str | None = field(default_factory=lambda: os.environ.get("DEVIN_API_KEY"))
    backend: str = field(default_factory=lambda: os.environ.get("PATENTLOOP_BACKEND", "devin"))
    devin_timeout_seconds: float = field(default_factory=lambda: float(os.environ.get("DEVIN_TIMEOUT_SECONDS", "1500")))
    devin_poll_interval: float = field(default_factory=lambda: float(os.environ.get("DEVIN_POLL_INTERVAL", "2")))
    devin_max_concurrent: int = field(default_factory=lambda: int(os.environ.get("DEVIN_MAX_CONCURRENT", "5")))


def require_live_keys(settings: Settings | None = None) -> None:
    """Fail before any live work if the required credentials are absent."""
    settings = settings or Settings()
    missing = []
    if settings.backend == "openai" and not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if settings.backend == "devin" and not settings.devin_api_key:
        missing.append("DEVIN_API_KEY")
    if not settings.uspto_api_key and not settings.devin_api_key:
        missing.append("USPTO_ODP_API_KEY or DEVIN_API_KEY (patent search)")
    if missing:
        raise RuntimeError(
            "PatentLoop live run requires missing environment key(s): "
            + ", ".join(missing)
        )
