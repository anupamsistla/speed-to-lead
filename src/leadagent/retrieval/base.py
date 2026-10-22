"""Retrieval interface. BM25 today; a pgvector implementation can replace it later."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from leadagent.config.schemas import KnowledgeDoc


class Hit(BaseModel):
    source: str  # knowledge file the text came from, e.g. "knowledge/faq.md"
    heading: str
    text: str
    score: float


class Retriever(Protocol):
    def index(self, docs: list[KnowledgeDoc]) -> None: ...

    def search(self, query: str, k: int = 3) -> list[Hit]:
        """Return up to k hits, best first. Every hit carries its source file."""
        ...
