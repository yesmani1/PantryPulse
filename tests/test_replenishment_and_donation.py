"""Local deterministic replenishment and donation safety contracts."""

from datetime import date, datetime, timedelta, timezone

from pantrypulse.schemas import (
    Category,
    CheckDonationEligibilityRequest,
    CreateShoppingListRequest,
    DateType,
    DepletionForecast,
    DonationStatus,
    ExpirySource,
    ItemStatus,
    PantryItem,
    RecipeIngredient,
    RequestDonationRequest,
)
from pantrypulse.tools.domain import (
    check_donation_eligibility,
    create_shopping_list,
    predict_consumption,
    request_donation,
)


def _item(item_id: str, category: Category, **overrides) -> PantryItem:
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    values = dict(household_id="h", item_id=item_id, name="Milk", category=category,
        quantity=1, unit="pack", purchase_date=date(2026, 9, 4), expiry_date=date(2026, 9, 10),
        date_type=DateType.ESTIMATED, expiry_source=ExpirySource.SHELF_LIFE_TABLE,
        confidence=0.45, sealed=True, high_risk=False, status=ItemStatus.ACTIVE,
        created_at=now, updated_at=now)
    values.update(overrides)
    return PantryItem(**values)


def test_consumption_uses_transparent_defaults_and_stored_rate():
    from pantrypulse.schemas import PredictConsumptionRequest

    result = predict_consumption([
        _item("milk", Category.DAIRY),
        _item("rice", Category.PANTRY, name="Rice", estimated_daily_consumption=0.1),
    ], PredictConsumptionRequest(household_id="h"))
    by_id = {forecast.item_id: forecast for forecast in result.forecasts}
    assert by_id["milk"].estimated_daily_consumption == 0.25
    assert by_id["milk"].confidence == 0.45
    assert by_id["rice"].estimated_daily_consumption == 0.1
    assert by_id["rice"].confidence == 0.65


def test_consumption_uses_unit_safe_mass_and_volume_defaults():
    from pantrypulse.schemas import PredictConsumptionRequest

    result = predict_consumption([
        _item("beef", Category.MEAT, quantity=500, unit="g"),
        _item("milk", Category.DAIRY, quantity=1000, unit="mL"),
        _item("unknown", Category.PANTRY, quantity=500, unit="scoops"),
    ], PredictConsumptionRequest(household_id="h"))
    by_id = {forecast.item_id: forecast for forecast in result.forecasts}
    assert by_id["beef"].estimated_daily_consumption == 150
    assert by_id["milk"].estimated_daily_consumption == 250
    assert "unknown" not in by_id


def test_shopping_list_deduplicates_recipe_and_depletion_needs():
    forecast = DepletionForecast(item_id="milk", name="Milk", estimated_daily_consumption=0.25,
        estimated_depletion_date=date(2026, 9, 5), confidence=0.45, explanation="test")
    result = create_shopping_list(CreateShoppingListRequest(
        missing_ingredients=[
            RecipeIngredient(name="Milk", missing=True),
            RecipeIngredient(name="Onion", quantity=2, unit="each", missing=True),
        ],
        depleted_items=[forecast],
    ))
    assert [item.name for item in result.shopping_list.items] == ["Milk", "Onion"]
    assert result.shopping_list.items[0].reasons == ["needed for recipe", "likely to run out soon"]


def test_donation_rule_rejects_high_risk_use_by_and_unsealed_items():
    today = date(2026, 9, 4)
    candidates = check_donation_eligibility(CheckDonationEligibilityRequest(items=[
        _item("safe", Category.PANTRY, name="Beans", expiry_date=date(2026, 10, 4)),
        _item("risky", Category.DELI, name="Turkey", date_type=DateType.USE_BY, high_risk=True),
        _item("open", Category.PANTRY, name="Open beans", sealed=False),
    ]), today=today).candidates
    assert [candidate.eligible for candidate in candidates] == [True, False, False]


def test_mock_donation_dispatches_only_eligible_candidates():
    today = date(2026, 9, 4)
    candidates = check_donation_eligibility(CheckDonationEligibilityRequest(items=[
        _item("safe", Category.PANTRY, name="Beans", expiry_date=date(2026, 10, 4)),
        _item("open", Category.PANTRY, name="Open beans", sealed=False),
    ]), today=today).candidates
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    result = request_donation(RequestDonationRequest(
        household_id="h", candidates=candidates, pickup_window_start=now,
        pickup_window_end=now + timedelta(hours=1),
    ))
    assert result.donation_request.status is DonationStatus.PENDING
    assert result.donation_request.candidate_item_ids == ["safe"]
