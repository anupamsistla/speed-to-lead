from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from leadagent.adapters.base import Adapters
from leadagent.clock import Clock
from leadagent.config.schemas import CompanyBundle
from leadagent.models import ToolCall
from leadagent.retrieval.base import Retriever
from leadagent.routing import Router
from leadagent.session import LeadSession


@dataclass
class ToolContext:
    bundle: CompanyBundle
    session: LeadSession
    adapters: Adapters
    retriever: Retriever
    router: Router
    clock: Clock
    record: Callable[[ToolCall], None] | None = None
