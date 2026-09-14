"""Offline, repeatable preflight for the PantryPulse demo's core safety flows."""

from __future__ import annotations

from datetime import date

from pantrypulse.fixtures import load_expiry_risks, load_pantry_items
from pantrypulse.schemas import (
    Category,
    CheckExpiringItemsRequest,
    DateType,
    ExpirySource,
    ExtractedItem,
)
from pantrypulse.tools.domain import check_expiring_items, derive_high_risk
from pantrypulse.tools.ingestion import to_pantry_items


def main() -> None:
    """Fail fast when demo fixtures or core ingestion/safety rules regress."""
    items = load_pantry_items()
    risks = check_expiring_items(
        items, CheckExpiringItemsRequest(household_id="demo", as_of=date.today())
    ).risks
    assert risks, "The demo pantry must show a decision-worthy safety contrast."
    assert all(risk.date_type is not DateType.SELL_BY or risk.risk_level.value == "none" for risk in risks)

    extracted = ExtractedItem(
        name="Demo deli turkey", category=Category.DELI, quantity=1, unit="pack",
        date_type=DateType.ESTIMATED, expiry_source=ExpirySource.OCR,
        confidence=0.0, sealed=True,
    )
    stored = to_pantry_items([extracted], household_id="demo", purchase_date=date.today())[0]
    assert stored.high_risk is derive_high_risk(Category.DELI, "Demo deli turkey")
    assert stored.expiry_source is ExpirySource.SHELF_LIFE_TABLE

    fixture_risks = load_expiry_risks()
    assert any(risk.date_type is DateType.USE_BY for risk in fixture_risks)
    assert any(risk.date_type is DateType.BEST_BY for risk in fixture_risks)
    print("Demo preflight passed: fixtures, safety rules, and fallback ingestion are ready.")


if __name__ == "__main__":
    main()
