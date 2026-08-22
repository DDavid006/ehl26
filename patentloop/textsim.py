"""Deterministic text similarity used as a check on the LLM's judgement.

No embeddings service is involved: tf-idf vectors are built from the documents
actually retrieved during the run, so the numbers can be recomputed offline
from the stored raw responses. Both the research and patent-search agents blend
this lexical signal with the LLM's element-by-element comparison, and the
saturation detector uses it to measure how much successive pivots differ.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}")

STOPWORDS = frozenset(
    """
    the and for with that this from are was were which their such into than then
    other more most also have has had been being can could may might will would should
    use uses used using based comprising comprise comprises wherein said one two first
    second third least about between within said plurality thereof therein herein
    method system apparatus device means step steps configured according present
    invention embodiment embodiments example examples data information provide provided
    providing include includes including its it is as at by of in on to a an or not no
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in STOPWORDS]


def term_frequencies(text: str) -> Counter:
    return Counter(tokenize(text))


def inverse_document_frequency(documents: list[str]) -> dict[str, float]:
    total = max(len(documents), 1)
    seen: Counter = Counter()
    for doc in documents:
        for term in set(tokenize(doc)):
            seen[term] += 1
    return {term: math.log((total + 1) / (count + 0.5)) + 1.0 for term, count in seen.items()}


def _vector(text: str, idf: dict[str, float]) -> dict[str, float]:
    tf = term_frequencies(text)
    if not tf:
        return {}
    peak = max(tf.values())
    return {term: (count / peak) * idf.get(term, 1.0) for term, count in tf.items()}


def cosine(a: str, b: str, corpus: list[str] | None = None) -> float:
    """Tf-idf cosine similarity in [0, 1]."""

    idf = inverse_document_frequency(corpus if corpus else [a, b])
    va, vb = _vector(a, idf), _vector(b, idf)
    if not va or not vb:
        return 0.0
    shared = set(va) & set(vb)
    if not shared:
        return 0.0
    dot = sum(va[t] * vb[t] for t in shared)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return round(dot / (na * nb), 4) if na and nb else 0.0


def best_cosine(text: str, candidates: list[str], corpus: list[str] | None = None) -> float:
    """Similarity of ``text`` to its closest candidate."""

    pool = corpus if corpus else [text, *candidates]
    return max((cosine(text, c, pool) for c in candidates), default=0.0)
