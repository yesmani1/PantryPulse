"""BE-19 combines independent tool outputs into one safe action plan."""

from datetime import date

from pantrypulse.interface.rendering import render_combined_decision
from pantrypulse.schemas import DonationCandidate, RecipeSuggestion, ShoppingList, ShoppingListItem
from pantrypulse.tools.decisions import build_combined_decision


def test_combined_decision_collects_cook_shop_and_donate_actions():
    recipe = RecipeSuggestion(name="Rescue bowl", rescued_item_ids=["a"], rescue_count=1,
        missing_count=0, ingredients=[], instructions=["Cook"], preparation_minutes=10, ranking_rationale="test")
    decision = build_combined_decision([], recipe=recipe,
        shopping_list=ShoppingList(items=[ShoppingListItem(name="Milk", reasons=["test"])]),
        donation_candidates=[DonationCandidate(item_id="beans", name="Beans", eligible=True,
            reason="safe", quantity=1, unit="can", expiry_date=date(2026, 10, 1))])
    assert decision.actions == ("cook", "shop", "donate")
    rendered = render_combined_decision(decision)
    assert rendered is not None and "Cook:" in rendered and "Shop:" in rendered and "Donate:" in rendered


def test_no_action_combined_decision_stays_silent():
    decision = build_combined_decision([], recipe=None, shopping_list=ShoppingList(items=[]), donation_candidates=[])
    assert decision.actions == ("ignore",)
    assert render_combined_decision(decision) is None
