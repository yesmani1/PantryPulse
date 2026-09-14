"""Central model-provider selection for every PantryPulse agent.

Changing ``MODEL_PROVIDER`` in the ignored .env file is the only required
switch between local Ollama development and Bedrock production models.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pantrypulse.interface.config import ModelProvider, Settings


class AgentRole(StrEnum):
    """Model capability required by an agent invocation."""

    TEXT = "text"
    VISION = "vision"


class ProviderUnavailableError(RuntimeError):
    """A provider cannot be reached or is not configured for the selected role."""


def create_model(settings: Settings, role: AgentRole = AgentRole.TEXT) -> Any:
    """Return one explicit Strands model without exposing provider details.

    Agent and tool modules deliberately call this factory rather than importing
    BedrockModel or OllamaModel themselves.
    """
    if settings.model_provider is ModelProvider.OLLAMA:
        from strands.models.ollama import OllamaModel

        model_id = (
            settings.ollama_vision_model if role is AgentRole.VISION else settings.ollama_text_model
        )
        if not settings.ollama_host or not model_id:
            raise ProviderUnavailableError("Ollama host and model IDs must be configured.")
        return OllamaModel(
            host=settings.ollama_host,
            model_id=model_id,
            temperature=0.2,
            max_tokens=1000,
            keep_alive="0",
        )

    if settings.model_provider is ModelProvider.BEDROCK:
        from strands.models.bedrock import BedrockModel

        model_id = (
            settings.bedrock_vision_model if role is AgentRole.VISION else settings.bedrock_text_model
        )
        if not settings.bedrock_region or not model_id:
            raise ProviderUnavailableError("Bedrock region and model IDs must be configured.")
        return BedrockModel(
            model_id=model_id,
            region_name=settings.bedrock_region,
            temperature=0.2,
            max_tokens=1000,
        )

    raise ProviderUnavailableError("Unsupported model provider configuration.")


def verify_ollama(settings: Settings) -> None:
    """Fail with an operator-safe diagnostic if Ollama or required models are absent."""
    if settings.model_provider is not ModelProvider.OLLAMA:
        return
    try:
        from ollama import Client

        available = {entry.model for entry in Client(host=settings.ollama_host).list().models}
    except Exception as error:
        raise ProviderUnavailableError(
            "Ollama is unavailable. Start Ollama and verify OLLAMA_HOST."
        ) from error
    missing = {settings.ollama_text_model, settings.ollama_vision_model} - available
    if missing:
        raise ProviderUnavailableError(
            "Ollama models are missing: " + ", ".join(sorted(missing)) + ". Pull them before starting the bot."
        )


def invoke_vision_json(
    settings: Settings,
    image_bytes: bytes,
    prompt: str,
    *,
    schema: dict[str, Any] | None = None,
    model_id: str | None = None,
) -> str:
    """Return one schema-shaped vision response through the selected provider.

    This is the only non-agent boundary allowed to speak to a model SDK.
    ``model_id`` overrides the configured vision model, which is how the
    verification gate obtains a second, independent read of the same image.
    """
    if settings.model_provider is ModelProvider.OLLAMA:
        try:
            from ollama import Client

            # A crashed or overloaded local Ollama engine otherwise hangs the
            # calling thread forever with no feedback to the user; bound it.
            response = Client(host=settings.ollama_host, timeout=180.0).chat(
                model=model_id or settings.ollama_vision_model,
                messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
                format=schema,
                options={"temperature": 0.2},
                keep_alive="0",
            )
            return response.message.content
        except Exception as error:
            raise ProviderUnavailableError(
                "Local vision is unavailable. Start Ollama and check the configured vision model."
            ) from error
    if settings.model_provider is ModelProvider.BEDROCK:
        try:
            import json

            import boto3

            tool_name = "extract_grocery_items"
            client = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
            response = client.converse(
                modelId=model_id or settings.bedrock_vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"image": {"format": "jpeg", "source": {"bytes": image_bytes}}},
                            {"text": prompt},
                        ],
                    }
                ],
                toolConfig={
                    "tools": [
                        {
                            "toolSpec": {
                                "name": tool_name,
                                "description": "Return the extracted PantryPulse grocery items.",
                                "inputSchema": {"json": schema or {"type": "object"}},
                            }
                        }
                    ],
                    "toolChoice": {"tool": {"name": tool_name}},
                },
                inferenceConfig={"temperature": 0.2, "maxTokens": 1000},
            )
            for block in response["output"]["message"]["content"]:
                if "toolUse" in block:
                    return json.dumps(block["toolUse"]["input"])
            raise ProviderUnavailableError("Bedrock vision returned no structured tool output.")
        except ProviderUnavailableError:
            raise
        except Exception as error:
            raise ProviderUnavailableError(
                "Bedrock vision is unavailable. Check BEDROCK_REGION and the configured model ID."
            ) from error
    raise ProviderUnavailableError("Unsupported model provider configuration.")
