"""Provider-neutral image ingestion, validation, cache, and pantry conversion."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PIL import Image

from pantrypulse.schemas import (
    AnalyzeGroceryImageRequest,
    AnalyzeGroceryImageResponse,
    DateType,
    ExpirySource,
    ExtractedItem,
    PantryItem,
    ParseGS1BarcodeRequest,
)
from pantrypulse.tools.domain import derive_high_risk, parse_gs1_barcode
from pantrypulse.tools.shelf_life import estimate_shelf_life

# Two models describe the same product differently; this is the similarity below
# which they are treated as talking about different items entirely.
_NAME_MATCH_THRESHOLD = 0.5
logger = logging.getLogger(__name__)


class DevResponseCache:
    """Ignored local cache so repeated development tests never reinvoke a model."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def get(self, *, image_bytes: bytes, cache_key: str) -> AnalyzeGroceryImageResponse | None:
        path = self._path(image_bytes, cache_key)
        if not path.exists():
            logger.info("ingestion cache miss")
            return None
        logger.info("ingestion cache hit")
        return AnalyzeGroceryImageResponse.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, *, image_bytes: bytes, cache_key: str, response: AnalyzeGroceryImageResponse) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._path(image_bytes, cache_key).write_text(response.model_dump_json(), encoding="utf-8")

    def _path(self, image_bytes: bytes, cache_key: str) -> Path:
        digest = hashlib.sha256(cache_key.encode("utf-8") + image_bytes).hexdigest()
        return self._directory / f"{digest}.json"


def downscale_image(image_bytes: bytes, *, longest_edge: int = 1500) -> bytes:
    """Limit image dimensions before local or hosted vision inference."""
    with Image.open(BytesIO(image_bytes)) as image:
        image.thumbnail((longest_edge, longest_edge))
        output = BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue()


def analyze_grocery_image(
    request: AnalyzeGroceryImageRequest,
    *,
    invoke_vision: Callable[[bytes, str], Any],
    cache: DevResponseCache | None = None,
    cache_key: str = "",
) -> AnalyzeGroceryImageResponse:
    """Extract contract-shaped items through an injected vision invocation.

    The invocation boundary lets the same function use an Ollama-backed Strands
    agent or a fake in tests, and prevents tools from selecting providers.
    """
    prepared_image = downscale_image(request.image_bytes)
    if cache and cache_key:
        cached = cache.get(image_bytes=prepared_image, cache_key=cache_key)
        if cached:
            return cached
    prompt = (
        f"Read this {request.mode.value}. Return only the extracted grocery items as JSON "
        "matching the given schema. Never guess a printed expiry date; leave it null when "
        "absent. Never invent an item name that is not visibly printed on the image. "
        "purchase_date is almost never knowable from a photo of an item already in the "
        "fridge or pantry: leave it null (never a placeholder string, never an invented date) "
        "unless a purchase or transaction date is actually printed on a receipt."
    )
    raw = invoke_vision(prepared_image, prompt)
    if isinstance(raw, AnalyzeGroceryImageResponse):
        response = raw
    elif isinstance(raw, str):
        response = AnalyzeGroceryImageResponse.model_validate_json(raw)
    else:
        response = AnalyzeGroceryImageResponse.model_validate(raw)
    if cache and cache_key:
        cache.put(image_bytes=prepared_image, cache_key=cache_key, response=response)
    return response


def _name_tokens(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _similarity(left: str, right: str) -> float:
    """How likely two product names describe the same physical item.

    Shared words beat character similarity here, because the two models order
    and pad names differently: "Kirkland A2 Organic Whole Milk" against "Whole
    Milk (Kirkland Signature A2)" scores 0.31 by character sequence but 0.80 by
    shared words, while genuinely different products share no words at all.
    """
    left_tokens, right_tokens = _name_tokens(left), _name_tokens(right)
    overlap = 0.0
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return max(overlap, SequenceMatcher(None, left.lower(), right.lower()).ratio())


def _best_match(item: ExtractedItem, candidates: list[ExtractedItem]) -> ExtractedItem | None:
    """Pair an item with the same product in a second read, or nothing."""
    best, best_score = None, 0.0
    for candidate in candidates:
        if candidate.category is not item.category:
            continue
        score = _similarity(item.name, candidate.name)
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= _NAME_MATCH_THRESHOLD else None


def verify_extractions(
    primary: list[ExtractedItem], verifier: list[ExtractedItem]
) -> list[ExtractedItem]:
    """Keep a printed date only when two independent reads agree on it.

    Testing showed a single model reports wrong dates at high confidence, and
    that repeating one model over enhanced crops repeats its own misreads rather
    than correcting them. Two different models disagreeing, however, reliably
    marked the readings that were in fact wrong. So a date survives only on
    agreement; anything else falls back to the shelf-life estimate and is
    flagged for the household to confirm, which is the only step in the whole
    pipeline that does not depend on a model being right.
    """
    unmatched = list(verifier)
    verified: list[ExtractedItem] = []
    for item in primary:
        match = _best_match(item, unmatched)
        if match is not None:
            unmatched.remove(match)
        other_date = match.expiry_date if match is not None else None

        if item.expiry_date is None and other_date is None:
            # Agreement that nothing was readable. The tier-3 estimate that
            # to_pantry_items applies is already labelled as an estimate.
            verified.append(item)
        elif item.expiry_date is not None and item.expiry_date == other_date:
            verified.append(item)
        else:
            verified.append(
                item.model_copy(update={"expiry_date": None, "needs_confirmation": True})
            )
    return verified


def to_pantry_items(items: list[ExtractedItem], *, household_id: str, purchase_date=None) -> list[PantryItem]:
    """Apply fallback dates and the central high-risk rule before persistence."""
    now = datetime.now(timezone.utc)
    converted = []
    for extracted in items:
        # A photo of an item already in the fridge carries no purchase date; an
        # unknown purchase date defaults to today rather than a fabricated one.
        acquired = purchase_date or extracted.purchase_date or datetime.now(timezone.utc).date()
        gs1 = (
            parse_gs1_barcode(ParseGS1BarcodeRequest(raw_payload=extracted.gs1_payload))
            if extracted.gs1_payload
            else None
        )
        if gs1 and gs1.data.expiry_date is not None:
            expiry_date = gs1.data.expiry_date
            date_type, source, confidence = DateType.ESTIMATED, ExpirySource.GS1_BARCODE, 1.0
            gtin = gs1.data.gtin or extracted.gtin
            lot_number = gs1.data.lot_number or extracted.lot_number
        elif extracted.expiry_date is None:
            fallback = estimate_shelf_life(extracted.category, acquired)
            expiry_date, date_type, source, confidence = fallback.expiry_date, fallback.date_type, fallback.expiry_source, fallback.confidence
            gtin, lot_number = extracted.gtin, extracted.lot_number
        else:
            expiry_date, date_type, source, confidence = extracted.expiry_date, extracted.date_type, extracted.expiry_source, extracted.confidence
            gtin, lot_number = extracted.gtin, extracted.lot_number
        converted.append(PantryItem(household_id=household_id, item_id=str(uuid4()), name=extracted.name, category=extracted.category, quantity=extracted.quantity, unit=extracted.unit, purchase_date=acquired, expiry_date=expiry_date, date_type=date_type, expiry_source=source, confidence=confidence, sealed=extracted.sealed, high_risk=derive_high_risk(extracted.category, extracted.name), gtin=gtin, lot_number=lot_number, needs_confirmation=extracted.needs_confirmation, created_at=now, updated_at=now))
    return converted
