"""Rendering PantryItems, RecipeSuggestions, and ExpiryRisks into Telegram
message text (IF-3, IF-5, IF-8, IF-13).

Two rules drive the pantry rendering:

1. Never present a date without saying what kind of date it is. A bare
   "28 Aug" invites the exact misreading the product exists to correct.
2. Every row states where the date came from (IF-5). Users distrust apps
   that appear to grab dates out of thin air, so an estimate must look
   like an estimate.

Plain text, no parse_mode — item names come from receipts and would other-
wise need escaping.
"""

from pantrypulse.schemas import (
    DateType,
    ExpiryRisk,
    ExpirySource,
    PantryItem,
    RecipeSuggestion,
    RiskLevel,
    ShoppingList,
)
from pantrypulse.tools.decisions import CombinedDecision, DailyExpiryDecision


def render_rescue_stats(rescued_count: int, tossed_count: int, estimated_value_saved: float) -> str:
    """Render the compact impact line used in one combined daily message."""
    return (
        f"This month: {rescued_count} rescued, {tossed_count} tossed. "
        f"~${estimated_value_saved:.0f} saved."
    )


def render_rescue_stats_if_measured(stats) -> str | None:
    """The impact line, or nothing at all when nothing has been measured yet.

    The counter exists so impact is measured rather than asserted (CLAUDE.md),
    which cuts both ways: a household that has not pressed a feedback button
    yet has no impact to report, and "0 rescued, 0 tossed, ~$0 saved" asserts
    a result rather than reporting one. Silence until there is something true
    to say.
    """
    if stats is None or (stats.rescued_count == 0 and stats.tossed_count == 0):
        return None
    return render_rescue_stats(
        stats.rescued_count, stats.tossed_count, stats.estimated_value_saved
    )


def render_shopping_list(shopping_list: ShoppingList) -> str:
    """Render one transparent, deduplicated shopping list."""
    if not shopping_list.items:
        return "Your pantry is stocked for now."
    lines = ["Shopping list"]
    for item in shopping_list.items:
        quantity = _format_ingredient_quantity(item.quantity, item.unit)
        reason = "; ".join(item.reasons)
        lines.append(f"- {item.name}{f' ({quantity})' if quantity else ''} — {reason}")
    return "\n".join(lines)


# The two halves of the daily message. The headings do the work: one asks for
# action, the other explicitly removes the urgency people invent for
# themselves. Roughly a fifth of consumer food waste comes from reading a
# quality date as a safety deadline, so the wording is the product.
_SAFETY_HEADING = "Use these first"
_QUALITY_HEADING = "Still good — worth a look, not a bin"


def _risk_row(risk: ExpiryRisk) -> str:
    """One item inside the daily message: identity, date meaning, source, advice.

    expiry_source appears on every row without exception (CLAUDE.md): an
    estimate must never be able to pass for a date someone actually read.
    """
    label = format_date_label(risk.date_type, risk.expiry_date)
    source = _SOURCE_LABEL[risk.expiry_source]
    return f"• {risk.name} — {label} · {source}\n   {risk.guidance}"


def render_daily_expiry_check(decision: DailyExpiryDecision, stats=None) -> str | None:
    """Render one combined daily update, or ``None`` when silence is correct.

    One message per household per day, never one per item, and nothing at all
    when nothing needs attention -- an agent that stays quiet on a quiet day is
    behaving correctly, not failing.

    ``stats`` adds the rescue counter (IF-14) when there is something measured
    to report. It closes the loop the feedback buttons opened: what those taps
    were for.
    """
    if not decision.should_notify:
        return None

    sections: list[str] = []
    if decision.safety_actions:
        rows = "\n".join(_risk_row(risk) for risk in decision.safety_actions)
        sections.append(f"{_SAFETY_HEADING}\n{rows}")
    if decision.quality_checks:
        rows = "\n".join(_risk_row(risk) for risk in decision.quality_checks)
        sections.append(
            f"{_QUALITY_HEADING}\n{rows}\n"
            "   A Best Before date is about quality, not safety. Trust your "
            "eyes and nose before the calendar."
        )
    impact = render_rescue_stats_if_measured(stats)
    if impact:
        sections.append(impact)
    return "PantryPulse — today\n\n" + "\n\n".join(sections)


def render_combined_decision(decision: CombinedDecision) -> str | None:
    """Render one combined decision and preserve silence for no-action homes."""
    if not decision.expiry.should_notify and decision.actions == ("ignore",):
        return None
    lines = ["PantryPulse decision"]
    if decision.expiry.safety_actions:
        lines.append("Safety: " + ", ".join(risk.name for risk in decision.expiry.safety_actions))
    if decision.expiry.quality_checks:
        lines.append("Quality check: " + ", ".join(risk.name for risk in decision.expiry.quality_checks))
    if decision.recipe:
        lines.append(f"Cook: {decision.recipe.name} rescues {decision.recipe.rescue_count} item(s).")
    if decision.shopping_list.items:
        lines.append(f"Shop: {len(decision.shopping_list.items)} item(s) suggested.")
    eligible = sum(candidate.eligible for candidate in decision.donation_candidates)
    if eligible:
        lines.append(f"Donate: {eligible} item(s) are eligible for the local mock partner.")
    return "\n".join(lines)

# What kind of date this is. The wording carries the meaning: "Best Before"
# reads as quality, "Use By" reads as safety. Never a bare countdown.
_DATE_TYPE_LABEL = {
    DateType.USE_BY: "Use By {date}",
    DateType.BEST_BY: "Best Before {date}",
    DateType.SELL_BY: "Sell By {date}",
    DateType.ESTIMATED: "Est. {date}",
    DateType.NONE: "No expiry date",
}

# Where the date came from (IF-5). Shown on every row, without exception.
_SOURCE_LABEL = {
    ExpirySource.GS1_BARCODE: "scanned from barcode",
    ExpirySource.OCR: "read from package",
    ExpirySource.SHELF_LIFE_TABLE: "estimated from category",
    ExpirySource.USER_CONFIRMED: "you confirmed it",
}

_INGEST_TIER_LABEL = {
    ExpirySource.GS1_BARCODE: "tier 1",
    ExpirySource.OCR: "tier 2",
    ExpirySource.SHELF_LIFE_TABLE: "tier 3 fallback",
    ExpirySource.USER_CONFIRMED: "confirmed by you",
}

# Below this, an estimate is worth calling out as shaky rather than merely
# derived. Only meaningful for shelf_life_table items.
LOW_CONFIDENCE = 0.6


def format_quantity(item: PantryItem) -> str:
    """Drop the trailing .0 that float quantities carry: 500.0 g -> 500 g."""
    quantity = item.quantity
    number = f"{quantity:.0f}" if quantity == int(quantity) else f"{quantity:g}"
    return f"{number} {item.unit}"


def format_date_label(date_type: DateType, expiry_date) -> str:
    """The date phrase for one row: what kind of date it is, then when.

    The year is never dropped. Omitting it hid a two-year misread in live
    testing -- "Best Before 15 Apr" for a package that read 2027 and was stored
    as 2025 -- which is precisely the confusion this project exists to prevent.
    """
    label = _DATE_TYPE_LABEL[date_type]
    if expiry_date is None:
        return label
    # Built by hand rather than strftime: the no-pad day directive differs
    # between platforms (%-d on Linux, %#d on Windows).
    return label.format(
        date=f"{expiry_date.day} {expiry_date.strftime('%b')} {expiry_date.year}"
    )


def render_item(item: PantryItem) -> str:
    """One item as two lines: what it is, then what its date actually means."""
    label = format_date_label(item.date_type, item.expiry_date)

    notes = [_SOURCE_LABEL[item.expiry_source], _INGEST_TIER_LABEL[item.expiry_source]]

    if item.date_type is DateType.SELL_BY:
        # A retailer stock-rotation date is not a consumer deadline. Saying so
        # on the row is cheaper than explaining it after someone bins the milk.
        notes.append("retailer date, not yours")
    elif item.date_type is DateType.NONE:
        notes.append("keeps indefinitely")
    elif (
        item.expiry_source is ExpirySource.SHELF_LIFE_TABLE
        and item.confidence < LOW_CONFIDENCE
    ):
        notes.append("low confidence")

    row = f"{item.name} — {format_quantity(item)}\n   {label} · {' · '.join(notes)}"
    if item.needs_confirmation:
        # Two reads of the package disagreed, so neither date was trusted. Say so
        # rather than letting an estimate pass for something read off the label.
        row += "\n   ⚠ couldn't read the date reliably — please check it"
    return row


def render_ordered_items(items: list[PantryItem]) -> str:
    """Render external orders without presenting them as food on hand."""
    if not items:
        return ""
    return "Ordered - awaiting receipt\n" + "\n".join(f"- {item.name}" for item in items)


def render_pantry(items: list[PantryItem], ordered_items: list[PantryItem] | None = None) -> str:
    """The full pantry listing."""
    ordered_text = render_ordered_items(ordered_items or [])
    if not items:
        active = "Your pantry is empty. Send me a photo of a receipt to get started."
        return active + (f"\n\n{ordered_text}" if ordered_text else "")

    count = len(items)
    header = f"Your pantry — {count} item{'s' if count != 1 else ''}"
    active = header + "\n\n" + "\n\n".join(render_item(item) for item in items)
    return active + (f"\n\n{ordered_text}" if ordered_text else "")


def _format_ingredient_quantity(quantity: float | None, unit: str | None) -> str:
    """Ingredients, unlike pantry items, may carry no quantity at all."""
    if quantity is None:
        return ""
    number = f"{quantity:.0f}" if quantity == int(quantity) else f"{quantity:g}"
    return f"{number} {unit}".strip() if unit else number


def render_recipe(recipe: RecipeSuggestion) -> str:
    """A recipe card leading with the rescue count (CLAUDE.md convention):
    "Shakshuka — rescues 3 expiring items, missing 1"."""
    header = f"{recipe.name} — rescues {recipe.rescue_count} expiring item"
    header += "s" if recipe.rescue_count != 1 else ""
    header += f", missing {recipe.missing_count}" if recipe.missing_count else ""

    lines = []
    for ingredient in recipe.ingredients:
        amount = _format_ingredient_quantity(ingredient.quantity, ingredient.unit)
        marker = "missing" if ingredient.missing else "have"
        name = f"{ingredient.name} ({amount})" if amount else ingredient.name
        lines.append(f"  [{marker}] {name}")

    if recipe.optional_staples:
        lines.append("  [optional staple] " + ", ".join(recipe.optional_staples))

    steps = [f"{i}. {step}" for i, step in enumerate(recipe.instructions, start=1)]

    return (
        f"{header}\n"
        f"{recipe.preparation_minutes} min\n\n"
        + "\n".join(lines)
        + "\n\n"
        + "\n".join(steps)
    )


def is_actionable(risk: ExpiryRisk) -> bool:
    """A sell_by date is never a consumer deadline (CLAUDE.md) -- risk_level
    none means suppress entirely, not just soften the wording. Filter before
    rendering, not inside the renderer, so a suppressed risk is never even
    handed a message to format."""
    return risk.risk_level is not RiskLevel.NONE


def render_expiry_risk(risk: ExpiryRisk) -> str:
    """One at-risk item: what it is, what its date means, and the one-line
    guidance an ExpiryAgent would give. Never call this on a suppressed
    (risk_level=none) risk -- see is_actionable()."""
    source = _SOURCE_LABEL[risk.expiry_source]
    return f"{risk.name} — {format_date_label(risk.date_type, risk.expiry_date)} · {source}\n\n{risk.guidance}"
