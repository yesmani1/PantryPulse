"""Tests for the shared PantryPulse schema contract."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from pantrypulse.schemas import (
    AddInventoryItemsResponse,
    AddInventoryItemsRequest,
    AnalyzeGroceryImageResponse,
    AnalyzeGroceryImageRequest,
    Category,
    CheckDonationEligibilityResponse,
    CheckDonationEligibilityRequest,
    CheckExpiringItemsResponse,
    CheckExpiringItemsRequest,
    ClassifyDateLabelResponse,
    ClassifyDateLabelRequest,
    Confirmation,
    CreateShoppingListResponse,
    CreateShoppingListRequest,
    DateClassification,
    DateType,
    DonationRequest,
    DonationStatus,
    ExpirySource,
    ExtractedItem,
    FeedbackEvent,
    FeedbackResponse,
    FindRecipeResponse,
    FindRecipeRequest,
    GetInventoryResponse,
    GetInventoryRequest,
    GetRescueStatsResponse,
    GetRescueStatsRequest,
    ImageMode,
    ItemStatus,
    PantryItem,
    ParseGS1BarcodeResponse,
    ParseGS1BarcodeRequest,
    PredictConsumptionResponse,
    PredictConsumptionRequest,
    RecordFeedbackResponse,
    RecordFeedbackRequest,
    RequestDonationResponse,
    RequestDonationRequest,
    RescueStats,
    ShoppingList,
    UpdateInventoryItemResponse,
    UpdateInventoryItemRequest,
)


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def pantry_item(**overrides: object) -> PantryItem:
    values = {
        "household_id": "household-1",
        "item_id": "item-1",
        "name": "Greek yogurt",
        "category": Category.DAIRY,
        "quantity": 1.0,
        "unit": "tub",
        "purchase_date": date(2026, 8, 20),
        "expiry_date": date(2026, 8, 25),
        "date_type": DateType.BEST_BY,
        "expiry_source": ExpirySource.OCR,
        "confidence": 0.92,
        "sealed": True,
        "high_risk": False,
        "status": ItemStatus.ACTIVE,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return PantryItem.model_validate(values)


def test_pantry_item_json_round_trip() -> None:
    item = pantry_item()
    assert PantryItem.model_validate_json(item.model_dump_json()) == item


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_between_zero_and_one(confidence: float) -> None:
    with pytest.raises(ValidationError):
        pantry_item(confidence=confidence)


def test_quantity_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        pantry_item(quantity=-1)


def test_non_perishable_can_have_no_expiry() -> None:
    item = pantry_item(
        name="Honey",
        category=Category.NON_PERISHABLE,
        expiry_date=None,
        date_type=DateType.NONE,
    )
    assert item.expiry_date is None


def test_date_type_none_rejects_an_expiry_date() -> None:
    with pytest.raises(ValidationError):
        pantry_item(date_type=DateType.NONE)


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        pantry_item(created_at=datetime(2026, 8, 26, 12, 0))


def test_enum_values_match_the_build_spec() -> None:
    assert {value.value for value in DateType} == {
        "use_by",
        "best_by",
        "sell_by",
        "estimated",
        "none",
    }
    # The first three are the ingest tiers in build-spec 3.2. user_confirmed is
    # not a tier -- nothing resolves into it automatically; it records that a
    # person supplied the date after the two vision reads disagreed.
    assert {value.value for value in ExpirySource} == {
        "gs1_barcode",
        "ocr",
        "shelf_life_table",
        "user_confirmed",
    }


def test_every_tool_request_contract_can_be_instantiated() -> None:
    item = pantry_item()
    requests = [
        AnalyzeGroceryImageRequest(
            image_bytes=b"image", mode=ImageMode.RECEIPT, household_id="household-1"
        ),
        ParseGS1BarcodeRequest(raw_payload="010123456789012817260901"),
        ClassifyDateLabelRequest(label_text="BEST BY 08/25/26", category=Category.DAIRY),
        AddInventoryItemsRequest(items=[item], idempotency_key="update-1"),
        GetInventoryRequest(household_id="household-1"),
        UpdateInventoryItemRequest(
            household_id="household-1", item_id="item-1", patch={"quantity": 0.5}
        ),
        CheckExpiringItemsRequest(household_id="household-1"),
        PredictConsumptionRequest(household_id="household-1"),
        FindRecipeRequest(at_risk_items=[], pantry=[item]),
        CreateShoppingListRequest(),
        CheckDonationEligibilityRequest(items=[item]),
        RequestDonationRequest(
            household_id="household-1",
            candidates=[
                {
                    "item_id": "item-1",
                    "name": "Greek yogurt",
                    "eligible": True,
                    "reason": "sealed with sufficient shelf life",
                    "quantity": 1,
                    "unit": "tub",
                    "expiry_date": date(2026, 9, 1),
                }
            ],
            pickup_window_start=NOW,
            pickup_window_end=datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc),
        ),
        RecordFeedbackRequest(
            household_id="household-1",
            item_id="item-1",
            response=FeedbackResponse.USED,
        ),
        GetRescueStatsRequest(household_id="household-1", period="2026-08"),
    ]

    for request in requests:
        assert type(request).model_validate_json(request.model_dump_json()) == request


def test_every_tool_response_contract_can_be_instantiated() -> None:
    item = pantry_item()
    confirmation = Confirmation(success=True, message="saved")
    donation = DonationRequest(
        request_id="donation-1",
        household_id="household-1",
        candidate_item_ids=["item-1"],
        pickup_window_start=NOW,
        pickup_window_end=datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc),
        status=DonationStatus.PENDING,
    )
    responses = [
        AnalyzeGroceryImageResponse(items=[]),
        ParseGS1BarcodeResponse(data={"raw_payload": "0101234567890128"}),
        ClassifyDateLabelResponse(
            classification=DateClassification(
                date_type=DateType.BEST_BY,
                confidence=0.95,
                safety_guidance="Check quality before using.",
                explanation="Best By describes quality, not safety.",
            )
        ),
        AddInventoryItemsResponse(confirmation=confirmation, item_ids=["item-1"]),
        GetInventoryResponse(items=[item]),
        UpdateInventoryItemResponse(item=item),
        CheckExpiringItemsResponse(risks=[]),
        PredictConsumptionResponse(forecasts=[]),
        FindRecipeResponse(suggestion=None),
        CreateShoppingListResponse(shopping_list=ShoppingList(items=[])),
        CheckDonationEligibilityResponse(candidates=[]),
        RequestDonationResponse(donation_request=donation),
        RecordFeedbackResponse(
            confirmation=confirmation,
            event=FeedbackEvent(
                household_id="household-1",
                event_id="feedback-1",
                item_id="item-1",
                response=FeedbackResponse.USED,
                estimated_value=4.5,
                timestamp=NOW,
            ),
        ),
        GetRescueStatsResponse(
            stats=RescueStats(
                household_id="household-1",
                period="2026-08",
                rescued_count=1,
                tossed_count=0,
                estimated_value_saved=4.5,
            )
        ),
    ]

    for response in responses:
        assert type(response).model_validate_json(response.model_dump_json()) == response


def test_needs_confirmation_defaults_to_false_and_round_trips():
    """The cross-model verification gate marks items whose printed date could
    not be trusted. Absent that gate, nothing is flagged."""
    item = pantry_item()
    assert item.needs_confirmation is False

    flagged = pantry_item(needs_confirmation=True)
    assert PantryItem.model_validate_json(flagged.model_dump_json()).needs_confirmation


def test_extracted_item_carries_the_confirmation_flag_and_optional_purchase_date():
    """A photo of an item already in the pantry cannot reveal its purchase date,
    so ExtractedItem must accept its absence rather than inviting a placeholder."""
    extracted = ExtractedItem(
        name="Organic Chicken Stock",
        category=Category.PANTRY,
        quantity=1.0,
        unit="carton",
        date_type=DateType.BEST_BY,
        expiry_source=ExpirySource.OCR,
        confidence=0.5,
        sealed=True,
    )
    assert extracted.purchase_date is None
    assert extracted.needs_confirmation is False
    assert ExtractedItem.model_validate_json(extracted.model_dump_json()) == extracted
