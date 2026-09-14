from types import SimpleNamespace

import pytest

from pantrypulse.evaluation import metric_summary, tool_topology_score


def test_metric_summary_keeps_aggregate_provider_metrics():
    result = SimpleNamespace(metrics=SimpleNamespace(get_summary=lambda: {"tokens": 12, "success": 1}))
    assert metric_summary(result) == {"tokens": 12, "success": 1}


def test_metric_summary_requires_supported_result():
    with pytest.raises(ValueError, match="metrics"):
        metric_summary(object())


def test_tool_topology_requires_all_specialists():
    assert tool_topology_score(SimpleNamespace(tool_names=["extraction_agent", "expiry_agent", "recipe_agent", "replenishment_agent", "donation_agent"])) == (5, 5)
