"""Deterministic PantryPulse domain tools used by agents and Telegram.

Safety decisions are rules, not model guesses. Language models may explain or
format these results but may not change their eligibility or risk outcome.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from pantrypulse.schemas import (
    Category, CheckDonationEligibilityRequest, CheckDonationEligibilityResponse,
    CheckExpiringItemsRequest, CheckExpiringItemsResponse, CreateShoppingListRequest,
    CreateShoppingListResponse, DateClassification, DateType, DepletionForecast,
    DonationCandidate, DonationRequest, DonationStatus, ExpiryRisk, FeedbackResponse,
    FindRecipeRequest, FindRecipeResponse, GS1Data, GetInventoryRequest,
    InventoryItemPatch, ItemStatus, PantryItem, ParseGS1BarcodeRequest,
    ParseGS1BarcodeResponse, PredictConsumptionRequest, PredictConsumptionResponse,
    RecipeIngredient, RecipeSuggestion, RequestDonationRequest, RequestDonationResponse,
    RiskLevel, ShoppingList, ShoppingListItem,
)


HIGH_RISK_CATEGORIES = {Category.MEAT, Category.DELI}
_COUNT_CONSUMPTION_PER_DAY = {Category.DAIRY: 0.25, Category.PRODUCE: 0.2, Category.MEAT: 0.15, Category.DELI: 0.15, Category.BAKERY: 0.2}
_UNIT_CONSUMPTION_PER_DAY = {
    "g": 150.0,
    "kg": 0.15,
    "ml": 250.0,
    "l": 0.25,
    "cup": 1.0,
    "cups": 1.0,
    "gallon": 0.0625,
    "gal": 0.0625,
}
_COUNT_UNITS = {"item", "items", "pack", "packs", "can", "cans", "egg", "eggs", "loaf", "loaves", "banana", "bananas", "bottle", "bottles", "roll", "rolls", "pizza", "pizzas", "tub", "tubs", "bunch", "bunches", "head", "heads", "whole", "each"}
_SAFE_DONATION_CATEGORIES = {Category.PANTRY, Category.FROZEN, Category.BAKERY, Category.NON_PERISHABLE}


def derive_high_risk(category: Category, name: str = "") -> bool:
    """Return the conservative high-risk flag used by expiry and donation rules."""
    normalized = name.lower()
    return category in HIGH_RISK_CATEGORIES or any(
        phrase in normalized for phrase in ("soft cheese", "ready-to-eat", "ready to eat", "raw ")
    )


def parse_gs1_barcode(request: ParseGS1BarcodeRequest) -> ParseGS1BarcodeResponse:
    """Parse GS1 AIs 01 (GTIN), 10 (lot), and 17 (YYMMDD expiry) deterministically."""
    raw = request.raw_payload.replace("(", "").replace(")", "")
    match_gtin = re.search(r"01(\d{14})", raw)
    match_expiry = re.search(r"17(\d{6})", raw)
    # AI 10 is variable-length. Start after a known fixed-length AI so a
    # coincidental ``10`` inside the 14-digit GTIN is never mistaken for a lot.
    lot_search_start = match_expiry.end() if match_expiry else match_gtin.end() if match_gtin else 0
    match_lot = re.search(r"10([^\x1d]+)", raw[lot_search_start:])
    expiry = None
    if match_expiry:
        encoded = match_expiry.group(1)
        try:
            expiry = date(2000 + int(encoded[:2]), int(encoded[2:4]), int(encoded[4:]))
        except ValueError:
            expiry = None
    return ParseGS1BarcodeResponse(data=GS1Data(
        raw_payload=request.raw_payload,
        gtin=match_gtin.group(1) if match_gtin else None,
        lot_number=match_lot.group(1).strip() if match_lot else None,
        expiry_date=expiry,
    ))


def classify_date_label(label_text: str, category: Category) -> DateClassification:
    """Classify printed date language conservatively without relying on a model."""
    text = label_text.lower()
    if "use by" in text or "use-by" in text:
        return DateClassification(date_type=DateType.USE_BY, confidence=0.95, safety_guidance="Treat this as a safety date; do not consume after it.", explanation="The label explicitly says Use By.")
    if "best before" in text or "best by" in text:
        return DateClassification(date_type=DateType.BEST_BY, confidence=0.95, safety_guidance="This is a quality date; check quality after the date rather than discarding automatically.", explanation="The label explicitly identifies a quality date.")
    if "sell by" in text or "sell-by" in text:
        return DateClassification(date_type=DateType.SELL_BY, confidence=0.95, safety_guidance="This retailer stock date is not a consumer safety deadline.", explanation="The label explicitly says Sell By.")
    return DateClassification(date_type=DateType.ESTIMATED, confidence=0.35, safety_guidance="The date wording is unclear; treat the estimate cautiously.", explanation=f"No recognised date phrase was found for {category.value}.")


def check_expiring_items(items: list[PantryItem], request: CheckExpiringItemsRequest) -> CheckExpiringItemsResponse:
    """Apply date-type-specific expiry rules; Best By and Sell By never count down."""
    today = request.as_of or date.today()
    risks: list[ExpiryRisk] = []
    for item in items:
        if item.status is not ItemStatus.ACTIVE:
            continue
        if item.date_type in {DateType.NONE, DateType.SELL_BY} or item.expiry_date is None:
            level, days, guidance = RiskLevel.NONE, None, "No consumer expiry action is needed."
        else:
            days = (item.expiry_date - today).days
            if item.date_type is DateType.BEST_BY:
                level = RiskLevel.LOW if days < 0 else RiskLevel.NONE
                guidance = "Past its Best Before date: check quality before using; it is not automatically unsafe." if days < 0 else "Best Before is a quality date; no alert before it passes."
            elif item.date_type is DateType.USE_BY:
                level = RiskLevel.HIGH if item.high_risk and days <= 1 else RiskLevel.MEDIUM if days <= 1 else RiskLevel.LOW if days <= 3 else RiskLevel.NONE
                guidance = "Use promptly; this is a safety date." if level is not RiskLevel.NONE else "No immediate action is needed."
            else:
                level = RiskLevel.MEDIUM if days <= 0 else RiskLevel.LOW if days <= 2 else RiskLevel.NONE
                guidance = "This is a low-confidence estimate; inspect before using." if level is not RiskLevel.NONE else "No immediate action is needed."
        risks.append(ExpiryRisk(item_id=item.item_id, name=item.name, date_type=item.date_type, expiry_date=item.expiry_date, expiry_source=item.expiry_source, confidence=item.confidence, high_risk=item.high_risk, risk_level=level, days_from_expiry=days, guidance=guidance, explanation=f"{item.date_type.value} rule applied."))
    return CheckExpiringItemsResponse(risks=risks)


def predict_consumption(items: list[PantryItem], request: PredictConsumptionRequest) -> PredictConsumptionResponse:
    """Produce only unit-compatible depletion forecasts; never invent a conversion."""
    forecasts = []
    for item in items:
        if item.status is not ItemStatus.ACTIVE or item.quantity <= 0:
            continue
        rate = item.estimated_daily_consumption or _default_consumption_rate(item)
        if not rate:
            continue
        depletion = date.today() + timedelta(days=max(1, round(item.quantity / rate)))
        forecasts.append(DepletionForecast(item_id=item.item_id, name=item.name, estimated_daily_consumption=rate, estimated_depletion_date=depletion, confidence=0.45 if item.estimated_daily_consumption is None else 0.65, explanation="Category default consumption estimate." if item.estimated_daily_consumption is None else "Based on the stored consumption estimate."))
    return PredictConsumptionResponse(forecasts=forecasts)


def _default_consumption_rate(item: PantryItem) -> float | None:
    """Return a default only when its unit matches the quantity being divided."""
    unit = item.unit.strip().lower()
    if unit in _UNIT_CONSUMPTION_PER_DAY:
        return _UNIT_CONSUMPTION_PER_DAY[unit]
    if unit in _COUNT_UNITS:
        return _COUNT_CONSUMPTION_PER_DAY.get(item.category)
    return None


def create_shopping_list(request: CreateShoppingListRequest) -> CreateShoppingListResponse:
    """Merge missing recipe ingredients and depleted pantry staples by name."""
    merged: dict[str, ShoppingListItem] = {}
    for ingredient in request.missing_ingredients:
        if not ingredient.missing:
            continue
        key = ingredient.name.lower()
        merged[key] = ShoppingListItem(name=ingredient.name, quantity=ingredient.quantity, unit=ingredient.unit, reasons=["needed for recipe"])
    for forecast in request.depleted_items:
        key = forecast.name.lower()
        current = merged.get(key)
        reason = "likely to run out soon"
        if current:
            current.reasons.append(reason)
        else:
            merged[key] = ShoppingListItem(name=forecast.name, reasons=[reason])
    return CreateShoppingListResponse(shopping_list=ShoppingList(items=sorted(merged.values(), key=lambda entry: entry.name.lower())))


def check_donation_eligibility(request: CheckDonationEligibilityRequest, *, today: date | None = None) -> CheckDonationEligibilityResponse:
    """Apply the stricter donation rule; an unsafe personal item is never donated."""
    today = today or date.today()
    candidates = []
    for item in request.items:
        eligible = item.sealed and item.category in _SAFE_DONATION_CATEGORIES and not (item.date_type is DateType.USE_BY and item.high_risk)
        if eligible and item.expiry_date is not None and (item.expiry_date - today).days < 2:
            eligible = False
        reason = "Sealed safe-category item with sufficient shelf life." if eligible else "Donation requires a sealed safe-category item with sufficient shelf life."
        candidates.append(DonationCandidate(item_id=item.item_id, name=item.name, eligible=eligible, reason=reason, quantity=item.quantity, unit=item.unit, expiry_date=item.expiry_date))
    return CheckDonationEligibilityResponse(candidates=candidates)


def request_donation(request: RequestDonationRequest) -> RequestDonationResponse:
    """Create a local mock-partner donation request; no external dispatch occurs."""
    candidates = [candidate for candidate in request.candidates if candidate.eligible]
    return RequestDonationResponse(donation_request=DonationRequest(request_id=str(uuid4()), household_id=request.household_id, candidate_item_ids=[candidate.item_id for candidate in candidates], pickup_window_start=request.pickup_window_start, pickup_window_end=request.pickup_window_end, status=DonationStatus.PENDING if candidates else DonationStatus.REJECTED))


def find_recipe(request: FindRecipeRequest) -> FindRecipeResponse:
    """Return a pantry-specific rescue recipe ranked by actionable risk first."""
    actionable = sorted((risk for risk in request.at_risk_items if risk.risk_level is not RiskLevel.NONE), key=lambda risk: ({RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}[risk.risk_level], risk.item_id))
    if not actionable:
        return FindRecipeResponse(suggestion=None)
    pantry_by_id = {item.item_id: item for item in request.pantry}
    rescued = [risk.item_id for risk in actionable if risk.item_id in pantry_by_id]
    ingredients = [RecipeIngredient(name=pantry_by_id[item_id].name, quantity=pantry_by_id[item_id].quantity, unit=pantry_by_id[item_id].unit, pantry_item_id=item_id) for item_id in rescued]
    lead = pantry_by_id[rescued[0]]
    recipe_name, instructions = _recipe_for_lead(lead.name, lead.category)
    return FindRecipeResponse(suggestion=RecipeSuggestion(name=recipe_name, rescued_item_ids=rescued, rescue_count=len(rescued), missing_count=0, ingredients=ingredients, instructions=instructions, preparation_minutes=20, ranking_rationale="Ranks safety-critical and soonest-expiring pantry items first."))


def _recipe_for_lead(name: str, category: Category) -> tuple[str, list[str]]:
    """Choose a deterministic preparation that names the actual rescue item."""
    if category in {Category.MEAT, Category.DELI}:
        return f"{name} rescue skillet", [f"Prepare {name} safely and cook it thoroughly.", "Add the other rescued ingredients and serve hot."]
    if category is Category.PRODUCE:
        return f"Roasted {name} rescue tray", [f"Wash and prepare {name}.", "Roast with the other rescued ingredients until tender."]
    if category is Category.BAKERY:
        return f"{name} pantry bake", [f"Tear or slice {name}.", "Bake with the other rescued ingredients until hot through."]
    return f"{name} pantry rescue bowl", [f"Prepare {name} using safe handling guidance.", "Combine with the other rescued ingredients and serve."]
