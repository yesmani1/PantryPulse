"""Report deterministic PantryPulse evaluation results without provider calls."""

from __future__ import annotations

from pantrypulse.schemas import Category, DateType
from pantrypulse.agents.pantry import build_agents
from pantrypulse.evaluation import tool_topology_score
from pantrypulse.interface.config import Settings
from pantrypulse.tools.domain import classify_date_label


DATE_CASES = (
    ("USE BY 10 Sep", DateType.USE_BY), ("Use By: 10/09", DateType.USE_BY),
    ("use-by", DateType.USE_BY), ("BEST BEFORE 10 Sep", DateType.BEST_BY),
    ("BEST BY 2026-09-10", DateType.BEST_BY), ("best by", DateType.BEST_BY),
    ("SELL BY 10 Sep", DateType.SELL_BY), ("Sell By: 10/09", DateType.SELL_BY),
    ("sell-by", DateType.SELL_BY), ("10/09/2026", DateType.ESTIMATED),
    ("EXP 10 Sep", DateType.ESTIMATED), ("Date: 2026-09-10", DateType.ESTIMATED),
    ("Packed 10 Sep", DateType.ESTIMATED), ("Fresh until 10 Sep", DateType.ESTIMATED),
    ("", DateType.ESTIMATED), ("batch L123", DateType.ESTIMATED),
    ("10 SEPT", DateType.ESTIMATED), ("Lot 987", DateType.ESTIMATED),
    ("Display until", DateType.ESTIMATED), ("Quality date", DateType.ESTIMATED),
)


def main() -> None:
    correct = sum(
        classify_date_label(label, Category.DAIRY).date_type is expected
        for label, expected in DATE_CASES
    )
    # Donation-specific branch coverage lives in the deterministic pytest suite;
    # the command intentionally reports only reproducible, provider-free metrics.
    print(f"date_label_accuracy={correct}/{len(DATE_CASES)}")
    print("donation_safety=covered by tests/test_replenishment_and_donation.py")
    selected, expected = tool_topology_score(build_agents(Settings(telegram_bot_token="evaluation")).pantry)
    print(f"tool_topology={selected}/{expected}")
    print("provider_metrics=run scripts/capture_bedrock_metrics.py --apply; output remains local")
    if correct != len(DATE_CASES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
