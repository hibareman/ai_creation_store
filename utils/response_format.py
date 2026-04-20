"""
Shared helpers for plain API JSON responses (no envelope).
"""
from __future__ import annotations

from typing import Any


ALLOWED_HTTP_STATUS_CODES = {200, 201, 204, 400, 401, 403, 404}

DEFAULT_SUCCESS_MESSAGE = "The operation was completed successfully."
DEFAULT_ERROR_MESSAGE = "An error occurred during processing."


def success_payload(
    data: Any = None,
    message: str = DEFAULT_SUCCESS_MESSAGE,
) -> Any:
    """
    Return plain success data without envelope.
    """
    return data


def error_payload(
    message: str = DEFAULT_ERROR_MESSAGE,
) -> dict:
    """
    Return a minimal plain error payload.
    """
    return {"detail": message}


def normalize_http_status_code(status_code: int) -> int:
    """
    Restrict response status codes to the agreed contract:
    200, 201, 204, 400, 401, 403, 404
    """
    if status_code in ALLOWED_HTTP_STATUS_CODES:
        return status_code

    if 200 <= status_code < 300:
        return 200

    if status_code == 401:
        return 401

    if status_code == 403:
        return 403

    if status_code == 404:
        return 404

    if 400 <= status_code < 500:
        return 400

    if status_code >= 500:
        return 400

    return 400


def is_enveloped_payload(payload: Any) -> bool:
    """
    Legacy helper: detect old wrapped payloads so middleware can unwrap them.
    """
    return (
        isinstance(payload, dict)
        and {"status", "message", "data"}.issubset(payload.keys())
        and payload.get("status") in {"success", "error"}
    )


def extract_error_message(
    payload: Any,
    default: str = DEFAULT_ERROR_MESSAGE,
) -> str:
    message = _extract_message_recursive(payload)
    return message or default


def extract_success_message(
    payload: Any,
    default: str = DEFAULT_SUCCESS_MESSAGE,
) -> str:
    if isinstance(payload, dict):
        if "message" in payload and isinstance(payload["message"], str):
            text = payload["message"].strip()
            if text:
                return text

        if "detail" in payload and isinstance(payload["detail"], str):
            text = payload["detail"].strip()
            if text:
                return text

    return default


def normalize_success_data(payload: Any) -> Any:
    """
    Unwrap legacy success envelope if present; otherwise return payload as-is.
    """
    if is_enveloped_payload(payload):
        return payload.get("data")

    if isinstance(payload, dict) and len(payload) == 1 and (
        "detail" in payload or "message" in payload
    ):
        return None

    return payload


def _extract_message_recursive(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, list):
        for item in value:
            message = _extract_message_recursive(item)
            if message:
                return message
        return ""

    if isinstance(value, dict):
        preferred_keys = ("message", "detail", "error", "non_field_errors")
        for key in preferred_keys:
            if key in value:
                message = _extract_message_recursive(value[key])
                if message:
                    return message

        for nested_value in value.values():
            message = _extract_message_recursive(nested_value)
            if message:
                return message

    return ""