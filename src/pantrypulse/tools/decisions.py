"""Deterministic daily decision context for one household notification.

This module combines already-classified risks rather than reclassifying dates.
A model may later phrase the decision, but may never change its safety actions.
"""

from __future__ import annotations

from dataclasses import dataclass

from pantrypulse.schemas import DonationCandidate, ExpiryRisk, RecipeSuggestion, RiskLevel, ShoppingList


_PRIORITY = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}


@dataclass(frozen=True)
class DailyExpiryDecision:
    """All expiry information suitable for exactly one household message."""

    actionable: tuple[ExpiryRisk, ...]
    safety_actions: tuple[ExpiryRisk, ...]
    quality_checks: tuple[ExpiryRisk, ...]

    @property
    def should_notify(self) -> bool:
        """Silence is correct when no item needs attention."""
        return bool(self.actionable)


@dataclass(frozen=True)
class CombinedDecision:
    """One transparent household action plan assembled from deterministic tools."""

    expiry: DailyExpiryDecision
    recipe: RecipeSuggestion | None
    shopping_list: ShoppingList
    donation_candidates: tuple[DonationCandidate, ...]

    @property
    def actions(self) -> tuple[str, ...]:
        """Return only meaningful, deduplicated controls for the household."""
        actions: list[str] = []
        if self.recipe is not None:
            actions.append("cook")
        if self.shopping_list.items:
            actions.append("shop")
        if any(candidate.eligible for candidate in self.donation_candidates):
            actions.append("donate")
        return tuple(actions) or ("ignore",)


def combine_expiry_issues(risks: list[ExpiryRisk]) -> DailyExpiryDecision:
    """Combine all actionable risks into one sorted decision context.

    High and medium risks represent safety actions. Low risks represent quality
    checks or low-confidence estimates. ``none`` risks are excluded, so Sell By
    dates and pre-date Best By labels never generate a message.
    """
    actionable = tuple(
        sorted(
            (risk for risk in risks if risk.risk_level is not RiskLevel.NONE),
            key=lambda risk: (_PRIORITY[risk.risk_level], risk.days_from_expiry or 0, risk.item_id),
        )
    )
    safety_actions = tuple(
        risk for risk in actionable if risk.risk_level in {RiskLevel.HIGH, RiskLevel.MEDIUM}
    )
    quality_checks = tuple(risk for risk in actionable if risk.risk_level is RiskLevel.LOW)
    return DailyExpiryDecision(actionable, safety_actions, quality_checks)


def build_combined_decision(
    risks: list[ExpiryRisk],
    *,
    recipe: RecipeSuggestion | None,
    shopping_list: ShoppingList,
    donation_candidates: list[DonationCandidate],
) -> CombinedDecision:
    """Combine deterministic outputs into one message-sized decision plan."""
    return CombinedDecision(
        expiry=combine_expiry_issues(risks),
        recipe=recipe,
        shopping_list=shopping_list,
        donation_candidates=tuple(donation_candidates),
    )
