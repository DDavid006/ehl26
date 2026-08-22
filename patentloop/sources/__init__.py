"""External data sources. Every one of these hits a live API."""

from .arxiv import ArxivSource
from .epo_ops import EpoOpsSource
from .github import GitHubSource
from .google_patents import GooglePatentsSource
from .patentsview import PatentsViewSource
from .semantic_scholar import SemanticScholarSource

__all__ = [
    "ArxivSource",
    "EpoOpsSource",
    "GitHubSource",
    "GooglePatentsSource",
    "PatentsViewSource",
    "SemanticScholarSource",
]
