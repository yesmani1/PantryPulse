"""Expiry intelligence: date meaning, risk rules, and one-message decisions."""

from datetime import date, datetime, timezone

from pantrypulse.interface.rendering import render_daily_expiry_check
from pantrypulse.schemas import Category, CheckExpiringItemsRequest, DateType, ExpirySource, ItemStatus, PantryItem
from pantrypulse.tools.decisions import combine_expiry_issues
from pantrypulse.tools.domain import check_expiring_items, classify_date_label


TODAY = date(2026, 9, 4)


def _item(name: str, date_type: DateType, expiry: date | None, *, high_risk: bool = False) -> PantryItem:
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    return PantryItem(household_id="h", item_id=name.lower().replace(" ", "-"), name=name,
        category=Category.DELI if high_risk else Category.DAIRY, quantity=1, unit="pack",
        purchase_date=TODAY, expiry_date=expiry, date_type=date_type, expiry_source=ExpirySource.OCR,
        confidence=0.9, sealed=True, high_risk=high_risk, status=ItemStatus.ACTIVE,
        created_at=now, updated_at=now)


def test_label_classification_recognizes_each_meaning():
    assert classify_date_label("USE BY 8 Sep", Category.DELI).date_type is DateType.USE_BY
    assert classify_date_label("BEST BEFORE 8 Sep", Category.DAIRY).date_type is DateType.BEST_BY
    assert classify_date_label("SELL BY 8 Sep", Category.DAIRY).date_type is DateType.SELL_BY
    assert classify_date_label("09/08", Category.DAIRY).date_type is DateType.ESTIMATED


def test_expiry_rules_suppress_pre_date_quality_and_retail_dates():
    risks = check_expiring_items([
        _item("Yogurt", DateType.BEST_BY, date(2026, 9, 6)),
        _item("Milk", DateType.SELL_BY, date(2026, 9, 1)),
        _item("Turkey", DateType.USE_BY, date(2026, 9, 5), high_risk=True),
    ], CheckExpiringItemsRequest(household_id="h", as_of=TODAY)).risks
    assert [risk.risk_level.value for risk in risks] == ["none", "none", "high"]


def test_combined_decision_creates_one_safety_and_quality_message():
    risks = check_expiring_items([
        _item("Deli turkey", DateType.USE_BY, date(2026, 9, 5), high_risk=True),
        _item("Yogurt", DateType.BEST_BY, date(2026, 9, 3)),
        _item("Milk", DateType.SELL_BY, date(2026, 9, 3)),
    ], CheckExpiringItemsRequest(household_id="h", as_of=TODAY)).risks
    decision = combine_expiry_issues(risks)
    rendered = render_daily_expiry_check(decision)
    assert len(decision.actionable) == 2
    assert len(decision.safety_actions) == 1
    assert len(decision.quality_checks) == 1
    assert rendered is not None and "Deli turkey" in rendered and "Yogurt" in rendered
    assert "Milk" not in rendered


def test_daily_decision_is_silent_for_no_risk_household():
    decision = combine_expiry_issues([])
    assert not decision.should_notify
    assert render_daily_expiry_check(decision) is None
