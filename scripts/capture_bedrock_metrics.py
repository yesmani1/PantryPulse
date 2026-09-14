"""Opt-in aggregate Bedrock trace capture; output stays in ignored .cache/."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from strands import Agent

from pantrypulse.agents.providers import AgentRole, create_model
from pantrypulse.evaluation import metric_summary
from pantrypulse.interface.config import ModelProvider, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="make one bounded Bedrock invocation")
    args = parser.parse_args()
    if not args.apply:
        print("Dry run: pass --apply to capture one aggregate Bedrock metrics trace.")
        return
    settings = load_settings()
    if settings.model_provider is not ModelProvider.BEDROCK:
        raise SystemExit("Set MODEL_PROVIDER=bedrock before live metrics capture.")
    result = Agent(model=create_model(settings, AgentRole.TEXT))("Reply with exactly: PantryPulse metrics check.")
    path = Path(".cache/evaluations/bedrock_metrics.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metric_summary(result), indent=2, default=str), encoding="utf-8")
    print(f"Aggregate metrics saved locally to {path}.")


if __name__ == "__main__":
    main()
