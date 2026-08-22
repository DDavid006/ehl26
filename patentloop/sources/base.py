"""Shared plumbing for source clients."""

from __future__ import annotations

from ..config import Config
from ..trace import Tracer


class Source:
    name = "source"
    agent = "research"

    def __init__(self, config: Config, tracer: Tracer):
        self.config = config
        self.tracer = tracer

    @property
    def available(self) -> bool:
        return True

    def _trace(self, query: str, response, count: int, iteration: int | None) -> None:
        self.tracer.api_call(self.agent, self.name, query, response, iteration, count)

    def _error(self, query: str, error: Exception, iteration: int | None) -> None:
        self.tracer.api_error(self.agent, self.name, query, str(error), iteration)
