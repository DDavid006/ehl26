"""Pluggable PatentLoop judge backends."""

from .devin_agent import DevinAgentBackend
from .openai_chat import OpenAIChatBackend

__all__ = ["DevinAgentBackend", "OpenAIChatBackend"]
