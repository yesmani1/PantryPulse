"""Shared Pydantic contracts for PantryPulse tools.

This module intentionally contains data contracts only. Agent, persistence,
AWS, and Telegram implementations must depend on these models rather than
defining their own wire formats.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]


class ContractModel(BaseModel):
    """Base configuration shared by all public PantryPulse contracts."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Category(str, Enum):
    DAIRY = "dairy"
    PRODUCE = "produce"
    MEAT = "meat"
    DELI = "deli"
    BAKERY = "bakery"
    PANTRY = "pantry"
    FROZEN = "frozen"
    HOUSEHOLD = "household"
    NON_PERISHABLE = "non_perishable"


class DateType(str, Enum):
    USE_BY = "use_by"
    BEST_BY = "best_by"
    SELL_BY = "sell_by"
    ESTIMATED = "estimated"
    NONE = "none"


class ExpirySource(str, Enum):
    GS1_BARCODE = "gs1_barcode"
    OCR = "ocr"
    SHELF_LIFE_TABLE = "shelf_life_table"
    # A date the household typed in themselves, after the vision reads either
    # disagreed or were wrong. More reliable than any of the above, and it must
    # not be displayed as an estimate.
    USER_CONFIRMED = "user_confirmed"


class ItemStatus(str, Enum):
    ACTIVE = "active"
    # The household has placed an order outside PantryPulse, but has not
    # received the item. Ordered rows are deliberately excluded from every
    # food-safety and pantry-decision calculation.
    ORDERED = "ordered"
    USED = "used"
    TOSSED = "tossed"
    DONATED = "donated"
    # Never in the pantry to begin with -- a misread item the household struck
    # out. Deliberately not TOSSED: tossed means real food went in the bin and
    # counts against the rescue figures, and charging someone for wasting food
    # that never existed would corrupt the one number this product measures.
    REMOVED = "removed"


class FeedbackResponse(str, Enum):
    USED = "used"
    STILL_GOOD = "still_good"
    TOSSED = "tossed"


class ImageMode(str, Enum):
    RECEIPT = "receipt"
    PACKAGE = "package"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DonationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class PantryItem(ContractModel):
    household_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: Category
    quantity: NonNegativeFloat
    unit: str = Field(min_length=1)
    purchase_date: date
    expiry_date: date | None = None
    date_type: DateType
    expiry_source: ExpirySource
    confidence: Confidence
    sealed: bool
    high_risk: bool
    gtin: str | None = None
    lot_number: str | None = None
    estimated_daily_consumption: NonNegativeFloat | None = None
    estimated_depletion_date: date | None = None
    status: ItemStatus = ItemStatus.ACTIVE
    # True when two independent vision reads disagreed about this item's printed
    # date, so no read was trusted. The date here is an estimate the household
    # has not yet corrected or accepted.
    needs_confirmation: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_dates(self) -> "PantryItem":
        if self.date_type is DateType.NONE and self.expiry_date is not None:
            raise ValueError("expiry_date must be absent when date_type is none")
        return self


class ExtractedItem(ContractModel):
    """One item as read from a photo. ``purchase_date`` is optional: a photo of
    an item already in the fridge gives no way to know when it was bought."""

    name: str = Field(min_length=1)
    category: Category
    quantity: NonNegativeFloat
    unit: str = Field(min_length=1)
    purchase_date: date | None = None
    expiry_date: date | None = None
    date_type: DateType
    expiry_source: ExpirySource
    confidence: Confidence
    sealed: bool
    label_text: str | None = None
    gs1_payload: str | None = None
    gtin: str | None = None
    lot_number: str | None = None
    # Set by the cross-model verification gate, not by the vision model itself.
    needs_confirmation: bool = False


class GS1Data(ContractModel):
    raw_payload: str = Field(min_length=1)
    gtin: str | None = None
    lot_number: str | None = None
    expiry_date: date | None = None
    unknown_application_identifiers: dict[str, str] = Field(default_factory=dict)


class DateClassification(ContractModel):
    date_type: DateType
    confidence: Confidence
    safety_guidance: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class InventoryItemPatch(ContractModel):
    name: str | None = Field(default=None, min_length=1)
    category: Category | None = None
    quantity: NonNegativeFloat | None = None
    unit: str | None = Field(default=None, min_length=1)
    purchase_date: date | None = None
    expiry_date: date | None = None
    date_type: DateType | None = None
    expiry_source: ExpirySource | None = None
    confidence: Confidence | None = None
    sealed: bool | None = None
    high_risk: bool | None = None
    gtin: str | None = None
    lot_number: str | None = None
    estimated_daily_consumption: NonNegativeFloat | None = None
    estimated_depletion_date: date | None = None
    status: ItemStatus | None = None
    needs_confirmation: bool | None = None


class ExpiryRisk(ContractModel):
    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    date_type: DateType
    expiry_date: date | None = None
    expiry_source: ExpirySource
    confidence: Confidence
    high_risk: bool
    risk_level: RiskLevel
    days_from_expiry: int | None = None
    guidance: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class DepletionForecast(ContractModel):
    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    estimated_daily_consumption: NonNegativeFloat
    estimated_depletion_date: date
    confidence: Confidence
    explanation: str = Field(min_length=1)


class RecipeIngredient(ContractModel):
    name: str = Field(min_length=1)
    quantity: NonNegativeFloat | None = None
    unit: str | None = None
    pantry_item_id: str | None = None
    missing: bool = False


class RecipeSuggestion(ContractModel):
    name: str = Field(min_length=1)
    rescued_item_ids: list[str]
    rescue_count: int = Field(ge=0)
    missing_ingredients: list[RecipeIngredient] = Field(default_factory=list)
    missing_count: int = Field(ge=0)
    ingredients: list[RecipeIngredient]
    instructions: list[str]
    preparation_minutes: int = Field(ge=0)
    ranking_rationale: str = Field(min_length=1)
    optional_staples: list[str] = Field(default_factory=list)


class GroundedRecipeResponse(ContractModel):
    """The bounded, non-authoritative wording returned by Recipe Agent."""

    title: str = Field(min_length=1, max_length=100)
    steps: list[str] = Field(min_length=3, max_length=6)
    preparation_minutes: int = Field(ge=1, le=180)
    optional_staples: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("optional_staples")
    @classmethod
    def only_basic_optional_staples(cls, staples: list[str]) -> list[str]:
        allowed = {"oil", "salt", "pepper", "water"}
        normalized = [staple.strip().lower() for staple in staples]
        if any(staple not in allowed for staple in normalized):
            raise ValueError("optional staples must be limited to oil, salt, pepper, or water")
        return normalized


class ShoppingListItem(ContractModel):
    name: str = Field(min_length=1)
    quantity: NonNegativeFloat | None = None
    unit: str | None = None
    reasons: list[str] = Field(default_factory=list)


class ShoppingList(ContractModel):
    items: list[ShoppingListItem]


class DonationCandidate(ContractModel):
    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    eligible: bool
    reason: str = Field(min_length=1)
    quantity: NonNegativeFloat
    unit: str = Field(min_length=1)
    expiry_date: date | None = None


class DonationRequest(ContractModel):
    request_id: str = Field(min_length=1)
    household_id: str = Field(min_length=1)
    candidate_item_ids: list[str]
    pickup_window_start: AwareDatetime
    pickup_window_end: AwareDatetime
    status: DonationStatus


class FeedbackEvent(ContractModel):
    household_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    response: FeedbackResponse
    estimated_value: NonNegativeFloat
    timestamp: AwareDatetime


class RescueStats(ContractModel):
    household_id: str = Field(min_length=1)
    period: str = Field(min_length=1)
    rescued_count: int = Field(ge=0)
    tossed_count: int = Field(ge=0)
    estimated_value_saved: NonNegativeFloat


class Confirmation(ContractModel):
    success: bool
    message: str = Field(min_length=1)


# Tool request/response contracts


class AnalyzeGroceryImageRequest(ContractModel):
    image_bytes: bytes
    mode: ImageMode
    household_id: str = Field(min_length=1)
    purchase_date: date | None = None


class AnalyzeGroceryImageResponse(ContractModel):
    items: list[ExtractedItem]


class ParseGS1BarcodeRequest(ContractModel):
    raw_payload: str = Field(min_length=1)


class ParseGS1BarcodeResponse(ContractModel):
    data: GS1Data


class ClassifyDateLabelRequest(ContractModel):
    label_text: str = Field(min_length=1)
    category: Category


class ClassifyDateLabelResponse(ContractModel):
    classification: DateClassification


class AddInventoryItemsRequest(ContractModel):
    items: list[PantryItem] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class AddInventoryItemsResponse(ContractModel):
    confirmation: Confirmation
    item_ids: list[str]


class GetInventoryRequest(ContractModel):
    household_id: str = Field(min_length=1)
    categories: list[Category] | None = None
    statuses: list[ItemStatus] | None = None


class GetInventoryResponse(ContractModel):
    items: list[PantryItem]


class UpdateInventoryItemRequest(ContractModel):
    household_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    patch: InventoryItemPatch


class UpdateInventoryItemResponse(ContractModel):
    item: PantryItem


class CheckExpiringItemsRequest(ContractModel):
    household_id: str = Field(min_length=1)
    as_of: date | None = None


class CheckExpiringItemsResponse(ContractModel):
    risks: list[ExpiryRisk]


class PredictConsumptionRequest(ContractModel):
    household_id: str = Field(min_length=1)


class PredictConsumptionResponse(ContractModel):
    forecasts: list[DepletionForecast]


class FindRecipeRequest(ContractModel):
    at_risk_items: list[ExpiryRisk]
    pantry: list[PantryItem]
    preferences: dict[str, Any] = Field(default_factory=dict)


class FindRecipeResponse(ContractModel):
    suggestion: RecipeSuggestion | None


class CreateShoppingListRequest(ContractModel):
    missing_ingredients: list[RecipeIngredient] = Field(default_factory=list)
    depleted_items: list[DepletionForecast] = Field(default_factory=list)


class CreateShoppingListResponse(ContractModel):
    shopping_list: ShoppingList


class CheckDonationEligibilityRequest(ContractModel):
    items: list[PantryItem]


class CheckDonationEligibilityResponse(ContractModel):
    candidates: list[DonationCandidate]


class RequestDonationRequest(ContractModel):
    household_id: str = Field(min_length=1)
    candidates: list[DonationCandidate] = Field(min_length=1)
    pickup_window_start: AwareDatetime
    pickup_window_end: AwareDatetime


class RequestDonationResponse(ContractModel):
    donation_request: DonationRequest


class RecordFeedbackRequest(ContractModel):
    household_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    response: FeedbackResponse
    estimated_value: NonNegativeFloat = 0.0


class RecordFeedbackResponse(ContractModel):
    confirmation: Confirmation
    event: FeedbackEvent


class GetRescueStatsRequest(ContractModel):
    household_id: str = Field(min_length=1)
    period: str = Field(min_length=1)


class GetRescueStatsResponse(ContractModel):
    stats: RescueStats
