"""Bot construction and entrypoint.

Run locally with:

    python -m pantrypulse.interface.bot

Long polling is the development surface. The webhook -> Lambda path in the build
spec is a deployment concern and does not change the handlers.
"""

import logging
import sys

from telegram import Update
from telegram.ext import Application, ContextTypes

from pantrypulse.interface import messages
from pantrypulse.interface.config import ConfigError, Settings, load_settings
from pantrypulse.interface.handlers import register_handlers
from pantrypulse.interface.services import create_services

logger = logging.getLogger(__name__)


async def on_error(object_: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Last line of defence. Tracebacks go to the log, never to the user."""
    logger.error("Unhandled error while processing update", exc_info=context.error)

    if isinstance(object_, Update) and object_.effective_chat is not None:
        try:
            await object_.effective_chat.send_message(messages.ERROR_GENERIC)
        except Exception:  # the apology itself failing must not re-enter the handler
            logger.exception("Failed to deliver the error message to the user")


def build_app(settings: Settings, *, services: object | None = None) -> Application:
    """Build a configured Application with every handler attached."""
    # Local vision calls can take a minute or more; a slow one must never block
    # other commands or other households behind it in the same process.
    app = Application.builder().token(settings.telegram_bot_token).concurrent_updates(True).build()
    app.bot_data["services"] = services if services is not None else create_services(settings)
    register_handlers(app)
    app.add_error_handler(on_error)
    return app


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        level=getattr(logging, level, logging.INFO),
    )
    # PTB polls continuously; httpx logs every request at INFO and drowns everything.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    configure_logging(settings.log_level)
    logger.info("Starting PantryPulse bot (polling)")

    app = build_app(settings)
    # Ignore anything queued while the bot was down — stale receipts are noise.
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
