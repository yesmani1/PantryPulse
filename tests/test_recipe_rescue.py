"""Recipe rescue prioritizes actionable safety risk and reports impact first."""

from datetime import date, datetime, timezone

from pantrypulse.interface.rendering import render_recipe
from pantrypulse.schemas import (
    Category, DateType, ExpiryRisk, ExpirySource, FindRecipeRequest, ItemStatus,
    PantryItem, RiskLevel,
)
from pantrypulse.tools.domain import find_recipe


def _item(item_id: str, name: str) -> PantryItem:
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    return PantryItem(household_id="h", item_id=item_id, name=name, category=Category.DELI,
        quantity=1, unit="pack", purchase_date=date(2026, 9, 1), expiry_date=date(2026, 9, 5),
        date_type=DateType.USE_BY, expiry_source=ExpirySource.OCR, confidence=0.9,
        sealed=True, high_risk=True, status=ItemStatus.ACTIVE, created_at=now, updated_at=now)


def _risk(item_id: str, name: str, level: RiskLevel) -> ExpiryRisk:
    return ExpiryRisk(item_id=item_id, name=name, date_type=DateType.USE_BY,
        expiry_date=date(2026, 9, 5), expiry_source=ExpirySource.OCR, confidence=0.9,
        high_risk=True, risk_level=level, days_from_expiry=1, guidance="Use promptly.", explanation="test")


def test_recipe_rescue_orders_safety_risk_and_leads_with_rescue_count():
    turkey, spinach = _item("turkey", "Turkey"), _item("spinach", "Spinach")
    suggestion = find_recipe(FindRecipeRequest(
        at_risk_items=[_risk("spinach", "Spinach", RiskLevel.LOW), _risk("turkey", "Turkey", RiskLevel.HIGH)],
        pantry=[turkey, spinach],
    )).suggestion
    assert suggestion is not None
    assert suggestion.rescued_item_ids == ["turkey", "spinach"]
    assert suggestion.rescue_count == 2
    assert render_recipe(suggestion).splitlines()[0].startswith("Turkey rescue skillet — rescues 2")


def test_recipe_returns_nothing_when_no_action_is_needed():
    assert find_recipe(FindRecipeRequest(at_risk_items=[], pantry=[])).suggestion is None


def test_recipe_name_is_specific_to_the_highest_priority_pantry_item():
    turkey = _item("turkey", "Turkey")
    chicken = _item("chicken", "Chicken")
    turkey_recipe = find_recipe(FindRecipeRequest(
        at_risk_items=[_risk("turkey", "Turkey", RiskLevel.HIGH)], pantry=[turkey]
    )).suggestion
    chicken_recipe = find_recipe(FindRecipeRequest(
        at_risk_items=[_risk("chicken", "Chicken", RiskLevel.HIGH)], pantry=[chicken]
    )).suggestion
    assert turkey_recipe is not None and chicken_recipe is not None
    assert turkey_recipe.name == "Turkey rescue skillet"
    assert chicken_recipe.name == "Chicken rescue skillet"
    assert turkey_recipe.name != chicken_recipe.name
