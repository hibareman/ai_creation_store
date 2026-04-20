"""
Raw-response parsing utilities for AI provider output.

This module is intentionally limited to parsing only:
- extract generated content from the provider raw response
- deserialize JSON content into a Python dict

No schema/business validation is performed here.
"""

from __future__ import annotations

import json
import re
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


def _extract_text_from_content_parts(content_parts: list[Any]) -> str:
    """
    Extract text from structured message content parts.

    Supported patterns include OpenAI-compatible text-part structures such as:
    - {"type": "text", "text": "..."}
    - {"text": "..."}
    - {"content": "..."}
    """
    text_parts: list[str] = []
    for part in content_parts:
        if isinstance(part, str):
            if part.strip():
                text_parts.append(part)
            continue

        if isinstance(part, Mapping):
            text_value = part.get("text")
            if isinstance(text_value, str) and text_value.strip():
                text_parts.append(text_value)
                continue

            content_value = part.get("content")
            if isinstance(content_value, str) and content_value.strip():
                text_parts.append(content_value)

    return "\n".join(text_parts).strip()


def _unwrap_fenced_block(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized

    full_fence = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", normalized, flags=re.IGNORECASE)
    if full_fence:
        return full_fence.group(1).strip()

    embedded_fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", normalized, flags=re.IGNORECASE)
    if embedded_fence:
        return embedded_fence.group(1).strip()

    return normalized


def _extract_braced_object_candidate(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return normalized

    start = normalized.find("{")
    end = normalized.rfind("}")
    if start != -1 and end != -1 and end > start:
        return normalized[start : end + 1].strip()

    return normalized


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

    text_content = ""
    if isinstance(content, list):
        text_content = _extract_text_from_content_parts(content)
    elif isinstance(content, str):
        text_content = content.strip()

    if not text_content:
        raise AIProviderParsingError(
            "Provider message content is empty or not a valid string/list of text parts."
        )

    candidates: list[str] = []
    for candidate in (
        text_content,
        _unwrap_fenced_block(text_content),
        _extract_braced_object_candidate(_unwrap_fenced_block(text_content)),
    ):
        normalized = candidate.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    decode_error_message: str | None = None
    non_object_seen = False

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            decode_error_message = exc.msg
            continue

        if isinstance(parsed, dict):
            return parsed

        non_object_seen = True

    if non_object_seen:
        raise AIProviderParsingError("Provider JSON content must deserialize to an object.")

    raise AIProviderParsingError(
        f"Provider content is not valid JSON: {decode_error_message or 'unknown JSON format error'}"
    )
