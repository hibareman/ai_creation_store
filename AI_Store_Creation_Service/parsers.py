"""
Raw-response parsing utilities for AI provider output.

This module is intentionally limited to parsing only:
- extract generated content from the provider raw response
- deserialize JSON content into a Python dict

No schema/business validation is performed here.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


class AIProviderParsingError(ValueError):
    """Raised when provider raw response cannot be parsed into a draft dict."""


def _extract_first_message_content(raw_response: Mapping[str, Any]) -> Any:
    """
    Extract the first assistant message content from Chat Completions response.

    Expected path:
    raw_response["choices"][0]["message"]["content"]
    """
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIProviderParsingError("Provider response is missing non-empty 'choices'.")

    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise AIProviderParsingError("Provider response 'choices[0]' is malformed.")

    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise AIProviderParsingError("Provider response is missing 'choices[0].message'.")

    if "content" not in message:
        raise AIProviderParsingError("Provider response is missing 'choices[0].message.content'.")

    return message["content"]


def parse_provider_raw_response_to_dict(raw_response: Mapping[str, Any]) -> dict[str, Any]:
    """
    Parse raw provider response into a Python dict payload.

    Raises:
        AIProviderParsingError: if content is missing, malformed, or invalid JSON.
    """
    if not isinstance(raw_response, Mapping):
        raise AIProviderParsingError("Provider raw response must be a mapping object.")

    content = _extract_first_message_content(raw_response)

    if isinstance(content, Mapping):
        return dict(content)

    if not isinstance(content, str) or not content.strip():
        raise AIProviderParsingError("Provider message content is empty or not a valid string.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIProviderParsingError(f"Provider content is not valid JSON: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise AIProviderParsingError("Provider JSON content must deserialize to an object.")

    return parsed
