"""Provider-neutral, safe-to-commit evaluation helpers."""

from __future__ import annotations

from typing import Any


def metric_summary(result: Any) -> dict[str, Any]:
    """Return aggregate SDK metrics without prompts, responses, or credentials."""
    metrics = getattr(result, "metrics", None)
    summary = getattr(metrics, "get_summary", None)
    if not callable(summary):
        raise ValueError("The provider result does not expose metrics.get_summary().")
    value = summary()
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "__dict__"):
        value = vars(value)
    if not isinstance(value, dict):
        value = {"summary": str(value)}
    return value


def tool_topology_score(agent: Any) -> tuple[int, int]:
    """Verify every required specialist is available to the orchestrator."""
    expected = {"extraction_agent", "expiry_agent", "recipe_agent", "replenishment_agent", "donation_agent"}
    actual = set(getattr(agent, "tool_names", []))
    return len(expected & actual), len(expected)
