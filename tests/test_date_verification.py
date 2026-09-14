"""Cross-model date verification.

Live testing showed one model returning a wrong date at 0.85 confidence, and
repeating that model over enhanced crops reproducing the identical misread three
times out of three. Two different models disagreeing was the only signal that
reliably marked a reading as untrustworthy, so agreement is the gate.
"""

from datetime import date

from pantrypulse.schemas import Category, DateType, ExpirySource, ExtractedItem
from pantrypulse.tools.ingestion import to_pantry_items, verify_extractions


def item(name: str, expiry: date | None, category: Category = Category.DAIRY) -> ExtractedItem:
    return ExtractedItem(
        name=name,
        category=category,
        quantity=1.0,
        unit="carton",
        expiry_date=expiry,
        date_type=DateType.BEST_BY if expiry else DateType.ESTIMATED,
        expiry_source=ExpirySource.OCR,
        confidence=0.9,
        sealed=True,
    )


def test_agreed_date_survives_unflagged():
    primary = [item("Kirkland A2 Organic Whole Milk", date(2026, 10, 28))]
    verifier = [item("Whole Milk (Kirkland Signature A2)", date(2026, 10, 28))]

    (result,) = verify_extractions(primary, verifier)

    assert result.expiry_date == date(2026, 10, 28)
    assert result.needs_confirmation is False


def test_disagreement_discards_the_date_rather_than_picking_a_winner():
    """Neither reading is trusted. The live failure was a confident wrong date,
    so preferring either model's answer would have persisted a wrong one."""
    primary = [item("Organic Chicken Stock", date(2025, 4, 15), Category.PANTRY)]
    verifier = [item("Chicken Stock, Organic", date(2027, 4, 16), Category.PANTRY)]

    (result,) = verify_extractions(primary, verifier)

    assert result.expiry_date is None
    assert result.needs_confirmation is True


def test_both_unreadable_is_agreement_and_stays_unflagged():
    """A shelf-life estimate is already labelled as an estimate in the UI;
    flagging every such item would make the flag meaningless."""
    primary = [item("Bellwether Farms Yogurt", None)]
    verifier = [item("Yogurt tub", None)]

    (result,) = verify_extractions(primary, verifier)

    assert result.expiry_date is None
    assert result.needs_confirmation is False


def test_one_model_reading_a_date_the_other_missed_is_not_agreement():
    primary = [item("Original Yogurt drink", date(2026, 12, 8))]
    verifier = [item("Yogurt drink", None)]

    (result,) = verify_extractions(primary, verifier)

    assert result.expiry_date is None
    assert result.needs_confirmation is True


def test_item_the_verifier_never_saw_cannot_be_confirmed():
    primary = [item("Original Yogurt drink", date(2026, 12, 8))]

    (result,) = verify_extractions(primary, [])

    assert result.expiry_date is None
    assert result.needs_confirmation is True


def test_items_of_different_categories_are_never_paired():
    """Similar names across categories must not be treated as the same product."""
    primary = [item("Organic Stock", date(2027, 4, 16), Category.PANTRY)]
    verifier = [item("Organic Stock", date(2027, 4, 16), Category.DAIRY)]

    (result,) = verify_extractions(primary, verifier)

    assert result.needs_confirmation is True


def test_flag_survives_conversion_into_the_stored_record():
    primary = [item("Organic Chicken Stock", date(2025, 4, 15), Category.PANTRY)]
    verifier = [item("Chicken Stock", date(2027, 4, 16), Category.PANTRY)]

    (stored,) = to_pantry_items(verify_extractions(primary, verifier), household_id="h")

    assert stored.needs_confirmation is True
    # The tier-3 fallback supplies a date, but it is labelled as an estimate.
    assert stored.expiry_source is ExpirySource.SHELF_LIFE_TABLE
