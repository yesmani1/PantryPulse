"""Configuration loading for the Telegram interface.

Secrets come from .env (gitignored) via python-dotenv. Nothing is hardcoded and
nothing is committed. A missing token is a configuration problem, not a crash:
it raises ConfigError, which bot.main() turns into a one-line message.
"""

import os
from dataclasses import dataclass
from enum import StrEnum

from dotenv import load_dotenv

TOKEN_VAR = "TELEGRAM_BOT_TOKEN"

# The value shipped in .env.example. Copying the example without editing it is a
# common enough mistake that it deserves its own error message.
PLACEHOLDER_TOKEN = "123456789:AAduMMy-pLaCeHoLdEr-ToKeN-ReplaceMe"


class ConfigError(Exception):
    """Configuration is missing or unusable. Message is shown to the operator."""


class ModelProvider(StrEnum):
    """Supported inference providers selected through MODEL_PROVIDER."""

    OLLAMA = "ollama"
    BEDROCK = "bedrock"


@dataclass(frozen=True)
class Settings:
    """Everything the bot needs to start."""

    telegram_bot_token: str
    log_level: str = "INFO"
    model_provider: ModelProvider = ModelProvider.OLLAMA
    ollama_host: str = "http://localhost:11434"
    ollama_text_model: str = "qwen2.5:7b"
    ollama_vision_model: str = "qwen2.5vl:3b"
    bedrock_region: str = "us-west-2"
    bedrock_text_model: str = "us.anthropic.claude-sonnet-4-6"
    bedrock_vision_model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def vision_model(self) -> str:
        """The model that produces the item list."""
        if self.model_provider is ModelProvider.OLLAMA:
            return self.ollama_vision_model
        return self.bedrock_vision_model

    def verifier_vision_model(self) -> str | None:
        """A second, different model used only to confirm printed dates.

        Returns None when no distinct second model is configured, which leaves
        every read unverified rather than silently comparing a model to itself.
        """
        if self.model_provider is ModelProvider.OLLAMA:
            return None  # one local vision model; a second would not be independent
        if self.bedrock_text_model == self.bedrock_vision_model:
            return None
        return self.bedrock_text_model


def load_settings() -> Settings:
    """Read .env into the environment and build Settings.

    Raises:
        ConfigError: the bot token is absent, empty, or still the placeholder.
    """
    load_dotenv()

    token = os.getenv(TOKEN_VAR, "").strip()
    if not token:
        raise ConfigError(
            f"{TOKEN_VAR} is not set. Copy .env.example to .env and paste the "
            "token @BotFather gave you."
        )
    if token == PLACEHOLDER_TOKEN:
        raise ConfigError(
            f"{TOKEN_VAR} is still the placeholder from .env.example. Replace it "
            "with the token @BotFather gave you."
        )

    provider_value = os.getenv("MODEL_PROVIDER", ModelProvider.OLLAMA).strip().lower()
    try:
        provider = ModelProvider(provider_value)
    except ValueError as error:
        raise ConfigError("MODEL_PROVIDER must be either 'ollama' or 'bedrock'.") from error

    return Settings(
        telegram_bot_token=token,
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        model_provider=provider,
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").strip(),
        ollama_text_model=os.getenv("OLLAMA_TEXT_MODEL", "qwen2.5:7b").strip(),
        ollama_vision_model=os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b").strip(),
        bedrock_region=os.getenv("BEDROCK_REGION", "us-west-2").strip(),
        bedrock_text_model=os.getenv(
            "BEDROCK_TEXT_MODEL", "us.anthropic.claude-sonnet-4-6"
        ).strip(),
        bedrock_vision_model=os.getenv(
            "BEDROCK_VISION_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ).strip(),
    )
