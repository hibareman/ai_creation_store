"""Feature flags for the future agentic AI Store Creation workflow."""

from __future__ import annotations

from django.conf import settings


def is_agentic_workflow_enabled() -> bool:
    """Return whether the agentic workflow is explicitly enabled."""
    return getattr(settings, "AI_AGENTIC_WORKFLOW_ENABLED", False) is True


__all__ = ["is_agentic_workflow_enabled"]
