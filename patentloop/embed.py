"""Lazy local sentence-transformers embeddings, cached for the process."""

from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=2)
def _model(model_name: str, cache_dir: str | None):
    from sentence_transformers import SentenceTransformer

    kwargs = {"device": "cpu"}
    if cache_dir:
        kwargs["cache_folder"] = cache_dir
    return SentenceTransformer(model_name, **kwargs)


def embed(
    texts: list[str],
    *,
    model_name: str | None = None,
    cache_dir: str | None = None,
) -> list[list[float]]:
    name = model_name or os.environ.get(
        "PATENTLOOP_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
    )
    cache = cache_dir or os.environ.get("PATENTLOOP_MODEL_CACHE")
    model = _model(name, cache)
    vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=False)
    return [vector.tolist() for vector in vectors]
