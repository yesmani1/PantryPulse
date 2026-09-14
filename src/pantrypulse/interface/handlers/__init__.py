"""Handler registration — the single place the bot learns what it responds to."""

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from pantrypulse.interface.handlers.commands import (
    demo,
    expiring,
    help_command,
    pantry,
    recipe,
    shopping,
    decision,
    start,
    today,
)
from pantrypulse.interface.handlers.feedback_actions import feedback_action
from pantrypulse.interface.handlers.inventory_actions import remove, remove_action
from pantrypulse.interface.handlers.photos import (
    ingestion_confirmation,
    photo,
    receive_date,
    request_date,
)
from pantrypulse.interface.handlers.recipe_actions import recipe_action
from pantrypulse.interface.handlers.shopping_actions import shopping_action, shopping_edit_text
from pantrypulse.interface.handlers.decision_actions import decision_action, donation_recipient_action
from pantrypulse.interface.handlers.order_actions import order_action, ordered_receipt_date

# Maps a MAIN_KEYBOARD button's exact label to the same function its /command
# equivalent uses -- a tap and typing the slash command are two paths into
# identical behaviour, not two things to keep in sync separately.
_KEYBOARD_ROUTES = {
    "Today": today,
    "Pantry": pantry,
    "Expiring": expiring,
    "Recipe": recipe,
    "Shopping": shopping,
    "Decision": decision,
    "Remove": remove,
}


def register_handlers(app: Application) -> None:
    """Attach every handler the bot serves."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("demo", demo))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("pantry", pantry))
    app.add_handler(CommandHandler("recipe", recipe))
    app.add_handler(CommandHandler("expiring", expiring))
    app.add_handler(CommandHandler("shopping", shopping))
    app.add_handler(CommandHandler("decision", decision))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    # Ordered before the general ingest handler: both match "ingest:", and only
    # the first matching handler in a group runs.
    app.add_handler(CallbackQueryHandler(request_date, pattern=r"^ingest:setdate:"))
    app.add_handler(CallbackQueryHandler(ingestion_confirmation, pattern=r"^ingest:"))
    app.add_handler(CallbackQueryHandler(recipe_action, pattern=r"^recipe:"))
    app.add_handler(CallbackQueryHandler(feedback_action, pattern=r"^feedback:"))
    app.add_handler(CallbackQueryHandler(remove_action, pattern=r"^remove:"))
    app.add_handler(CallbackQueryHandler(shopping_action, pattern=r"^shopping:"))
    app.add_handler(CallbackQueryHandler(order_action, pattern=r"^order:"))
    app.add_handler(CallbackQueryHandler(decision_action, pattern=r"^decision:"))
    app.add_handler(CallbackQueryHandler(donation_recipient_action, pattern=r"^donation:"))
    for label, handler in _KEYBOARD_ROUTES.items():
        app.add_handler(MessageHandler(filters.Text([label]), handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, shopping_edit_text))
    # A second group, because only one handler per group runs and both of these
    # free-text listeners must get a look at the message. Each is a no-op unless
    # its own conversation state is set.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ordered_receipt_date), group=2)
