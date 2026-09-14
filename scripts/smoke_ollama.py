"""Verify the configured local Strands/Ollama text provider."""

from strands import Agent

from pantrypulse.agents.providers import create_model, verify_ollama
from pantrypulse.interface.config import Settings


def main() -> None:
    settings = Settings(telegram_bot_token="local-smoke")
    verify_ollama(settings)
    result = Agent(model=create_model(settings))(
        "Reply with exactly: PantryPulse local smoke passed"
    )
    print(str(result))


if __name__ == "__main__":
    main()
