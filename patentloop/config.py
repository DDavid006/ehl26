"""Runtime configuration for PatentLoop.

Everything is read from the environment so a run can be reproduced from a
shell one-liner. Only ``ANTHROPIC_API_KEY`` is mandatory; the external data
sources that need keys degrade to the keyless ones.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"

# Decision-gate thresholds. Documented in README.md ("Verification").
NOVELTY_PASS = 55.0
OVERLAP_BLOCK = 45.0
# Two successive pivot proposals this similar (tf-idf cosine) count as the
# pivot space collapsing onto the same blocked territory.
PIVOT_CONVERGENCE = 0.55


class ConfigError(Exception):
    """Raised when the environment cannot support a real run."""


@dataclass
class Config:
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 4096
    max_iterations: int = 4
    runs_dir: Path = DEFAULT_RUNS_DIR
    results_per_query: int = 6
    request_timeout: int = 45
    # Optional keys for the sources that require registration.
    semantic_scholar_api_key: str | None = None
    patentsview_api_key: str | None = None
    epo_ops_key: str | None = None
    epo_ops_secret: str | None = None
    github_token: str | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set. PatentLoop calls the Anthropic API "
                "for every agent; export the key and re-run."
            )
        cfg = cls(
            anthropic_api_key=key,
            anthropic_model=os.environ.get("PATENTLOOP_MODEL", cls.anthropic_model),
            max_iterations=int(os.environ.get("PATENTLOOP_MAX_ITERATIONS", cls.max_iterations)),
            semantic_scholar_api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or None,
            patentsview_api_key=os.environ.get("PATENTSVIEW_API_KEY") or None,
            epo_ops_key=os.environ.get("EPO_OPS_KEY") or None,
            epo_ops_secret=os.environ.get("EPO_OPS_SECRET") or None,
            github_token=os.environ.get("GITHUB_TOKEN") or None,
        )
        for name, value in overrides.items():
            if value is not None:
                setattr(cfg, name, value)
        return cfg
