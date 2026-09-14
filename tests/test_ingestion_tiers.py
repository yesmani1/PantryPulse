"""Tier precedence is GS1, then printed OCR, then shelf-life estimates."""

from datetime import date

from pantrypulse.schemas import Category, DateType, ExpirySource, ExtractedItem
from pantrypulse.tools.ingestion import to_pantry_items


def _extracted(**overrides) -> ExtractedItem:
    values = dict(name="Milk", category=Category.DAIRY, quantity=1, unit="carton",
        purchase_date=date(2026, 9, 1), date_type=DateType.ESTIMATED,
        expiry_source=ExpirySource.OCR, confidence=0.8, sealed=True)
    values.update(overrides)
    return ExtractedItem(**values)


def test_gs1_expiry_beats_ocr_and_populates_identifier_fields():
    item = to_pantry_items([_extracted(
        expiry_date=date(2026, 9, 5),
        gs1_payload="01012345678901281726093010LOT9",
    )], household_id="h")[0]
    assert item.expiry_date == date(2026, 9, 30)
    assert item.expiry_source is ExpirySource.GS1_BARCODE
    assert item.gtin == "01234567890128"
    assert item.lot_number == "LOT9"


def test_ocr_beats_shelf_life_when_no_gs1_payload_exists():
    item = to_pantry_items([_extracted(expiry_date=date(2026, 9, 8))], household_id="h")[0]
    assert item.expiry_date == date(2026, 9, 8)
    assert item.expiry_source is ExpirySource.OCR


def test_shelf_life_is_final_fallback_when_no_date_is_extracted():
    item = to_pantry_items([_extracted()], household_id="h")[0]
    assert item.expiry_date == date(2026, 9, 8)
    assert item.expiry_source is ExpirySource.SHELF_LIFE_TABLE
