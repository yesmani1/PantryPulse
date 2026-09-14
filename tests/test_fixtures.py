"""S-4 / spec section 7 — every fixture validates, and the seven named items in
the section 7.3 demo scenario are in the exact states the spec requires.

Section 7.2's first rule is "fixtures conform to schemas.py"; per CLAUDE.md, a
fixture that fails to load means the contract moved without anyone saying so.
Loading every file here is that check.
"""

from datetime import date

import pytest

from pantrypulse import fixtures
from pantrypulse.schemas import DateType, ExpirySource, RiskLevel

TODAY = date(2026, 8, 26)


# ---------------------------------------------------------------------------
# 7.3 demo seed scenario — the exact states, not just the item names.
# ---------------------------------------------------------------------------


@pytest.fixture
def pantry():
    return fixtures.load_pantry_items(today=TODAY)


def _find(items, name):
    return next(i for i in items if i.name == name)


def test_yogurt_is_two_days_past_best_by(pantry):
    item = _find(pantry, "Greek Yogurt")
    assert item.date_type is DateType.BEST_BY
    assert (TODAY - item.expiry_date).days == 2


def test_turkey_is_due_tomorrow_and_high_risk(pantry):
    item = _find(pantry, "Sliced Turkey")
    assert item.date_type is DateType.USE_BY
    assert (item.expiry_date - TODAY).days == 1
    assert item.high_risk is True


def test_spinach_is_one_day_left_at_low_confidence(pantry):
    item = _find(pantry, "Baby Spinach")
    assert item.date_type is DateType.ESTIMATED
    assert (item.expiry_date - TODAY).days == 1
    assert item.confidence < 0.6


def test_milk_sell_by_has_already_passed(pantry):
    item = _find(pantry, "Whole Milk")
    assert item.date_type is DateType.SELL_BY
    assert item.expiry_date < TODAY


def test_honey_is_never_counted_down(pantry):
    item = _find(pantry, "Runny Honey")
    assert item.date_type is DateType.NONE
    assert item.expiry_date is None


def test_canned_tomatoes_are_sealed_and_donation_eligible_by_age(pantry):
    item = _find(pantry, "Canned Tomatoes")
    assert item.date_type is DateType.BEST_BY
    assert item.sealed is True
    # "8 months" per 7.3 -- allow the calendar-month rounding some slack.
    assert 200 <= (item.expiry_date - TODAY).days <= 260


def test_eggs_are_depleting_per_consumption_model(pantry):
    item = _find(pantry, "Free Range Eggs")
    assert item.date_type is DateType.ESTIMATED
    assert item.estimated_daily_consumption is not None
    assert item.estimated_depletion_date is not None
    assert item.estimated_depletion_date <= date(2026, 8, 28)


# ---------------------------------------------------------------------------
# The other seven files in 7.1.
# ---------------------------------------------------------------------------


def test_receipt_extraction_has_twelve_mixed_items():
    items = fixtures.load_extracted_items("extracted_items_receipt.json", today=TODAY)
    assert len(items) == 12
    assert len({i.date_type for i in items}) > 1
    assert len({i.expiry_source for i in items}) > 1


def test_package_extraction_has_one_gs1_hit():
    items = fixtures.load_extracted_items("extracted_items_package.json", today=TODAY)
    assert len(items) == 4
    gs1_items = [i for i in items if i.expiry_source is ExpirySource.GS1_BARCODE]
    assert len(gs1_items) == 1
    assert gs1_items[0].gtin is not None
    assert gs1_items[0].confidence == 1.0


def test_purchase_history_spans_sixty_days():
    items = fixtures.load_extracted_items("purchase_history_60d.json", today=TODAY)
    assert len(items) > 0
    span = (max(i.purchase_date for i in items) - min(i.purchase_date for i in items)).days
    assert span == 60


def test_expiry_risks_cover_the_deliberate_mix():
    risks = fixtures.load_expiry_risks(today=TODAY)
    by_type = {r.date_type: r for r in risks}

    assert by_type[DateType.BEST_BY].expiry_date < TODAY  # passed
    assert by_type[DateType.USE_BY].expiry_date > TODAY  # tomorrow
    assert by_type[DateType.SELL_BY].risk_level is RiskLevel.NONE  # suppressed
    assert by_type[DateType.ESTIMATED].confidence < 0.6  # low-confidence


def test_recipe_rescues_three_missing_one():
    recipe = fixtures.load_recipe_suggestion()
    assert recipe.name == "Shakshuka"
    assert recipe.rescue_count == 3
    assert len(recipe.rescued_item_ids) == 3
    assert recipe.missing_count == 1
    assert sum(i.missing for i in recipe.ingredients) == 1


def test_donation_candidates_reject_the_high_risk_use_by_item():
    """CLAUDE.md: donation eligibility must be stricter than personal-
    consumption advice, never looser. This is the fixture that proves it."""
    candidates = fixtures.load_donation_candidates(today=TODAY)
    assert sum(c.eligible for c in candidates) == 2

    rejected = [c for c in candidates if not c.eligible]
    assert len(rejected) == 1
    assert rejected[0].name == "Sliced Turkey"


def test_rescue_stats_show_tossed_count_declining():
    stats = fixtures.load_rescue_stats()
    assert len(stats) == 2
    earlier, later = sorted(stats, key=lambda s: s.period)
    assert later.tossed_count < earlier.tossed_count
    assert later.rescued_count > earlier.rescued_count
