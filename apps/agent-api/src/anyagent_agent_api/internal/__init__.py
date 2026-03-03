from __future__ import annotations

from .events import create_internal_events_router
from .skills import create_internal_skills_router

__all__ = ["create_internal_events_router", "create_internal_skills_router"]

