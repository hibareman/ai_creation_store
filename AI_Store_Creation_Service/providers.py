"""
AI provider contract layer.

This module defines the official abstraction for provider communication and
request execution. Prompt/message construction belongs to prompts.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .prompts import (
    build_generate_store_draft_messages,
    build_clarify_store_draft_messages,
    build_regenerate_store_draft_messages,
    build_regenerate_store_draft_section_messages,
)


ProviderRawResponse = dict[str, Any]


class AIProviderContract(ABC):
    @abstractmethod
    def generate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_store_description: str,
        available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        raise NotImplementedError

    @abstractmethod
    def clarify_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        current_draft: Mapping[str, Any],
        prompt: str,
        context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        raise NotImplementedError

    @abstractmethod
    def regenerate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        original_store_description: str,
        current_draft: Mapping[str, Any],
        clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
        available_theme_templates: Sequence[str] | None = None,
    ) -> ProviderRawResponse:
        raise NotImplementedError

    @abstractmethod
    def regenerate_store_draft_section(
        self,
        *,
        tenant_id: int,
        store_id: int,
        target_section: str,
        original_store_description: str,
        current_draft: Mapping[str, Any],
        clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
        available_theme_templates: Sequence[str] | None = None,
    ) -> ProviderRawResponse:
        raise NotImplementedError


def _post_json_request(
    *,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str] | None,
    timeout: int,
) -> ProviderRawResponse:
    request = Request(
        url=url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=dict(headers or {}),
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        response_body = response.read().decode("utf-8")
        return json.loads(response_body)


class OpenAIProviderClient(AIProviderContract):
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self.api_key = settings.AI_API_KEY
        self.model_name = settings.AI_MODEL_NAME
        self.timeout = settings.AI_TIMEOUT
        self.api_url = getattr(settings, "AI_API_URL", self.API_URL)
        self.http_referer = getattr(settings, "AI_HTTP_REFERER", "")
        self.app_title = getattr(settings, "AI_APP_TITLE", "")

    def _build_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ImproperlyConfigured(
                "AI_API_KEY is not configured. Set it in environment/.env before calling provider."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer.strip()

        if self.app_title:
            headers["X-Title"] = self.app_title.strip()

        return headers

    def _build_chat_payload(
        self,
        messages: list[dict[str, str]],
        *,
        include_response_format: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "provider": {
                "require_parameters": True,
            },
            "plugins": [
                {"id": "response-healing"},
            ],
            "temperature": 0.2,
        }

        if include_response_format:
            # Keep this for models/providers that support JSON object output.
            # The caller already retries without it if unsupported.
            payload["response_format"] = {"type": "json_object"}

        return payload

    @staticmethod
    def _is_response_format_unsupported_error(status_code: int, error_body: str) -> bool:
        if status_code not in {400, 404, 422}:
            return False

        normalized = (error_body or "").lower()
        indicators = (
            "response_format",
            "json_object",
            "unsupported parameter",
            "not supported",
            "unknown parameter",
            "invalid parameter",
        )
        return any(marker in normalized for marker in indicators)

    def _send_chat_completions_request(self, payload: Mapping[str, Any]) -> ProviderRawResponse:
        return _post_json_request(
            url=self.api_url,
            payload=payload,
            headers=self._build_headers(),
            timeout=self.timeout,
        )

    def _call_chat_completions(self, messages: list[dict[str, str]]) -> ProviderRawResponse:
        payload = self._build_chat_payload(messages, include_response_format=True)

        try:
            return self._send_chat_completions_request(payload)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")

            if self._is_response_format_unsupported_error(exc.code, error_body):
                retry_payload = self._build_chat_payload(
                    messages,
                    include_response_format=False,
                )
                try:
                    return self._send_chat_completions_request(retry_payload)
                except HTTPError as retry_exc:
                    retry_error_body = retry_exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Provider HTTP error {retry_exc.code}: {retry_error_body}"
                    ) from retry_exc
                except URLError as retry_exc:
                    raise RuntimeError(
                        f"Provider connection error: {retry_exc.reason}"
                    ) from retry_exc

            raise RuntimeError(f"Provider HTTP error {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Provider connection error: {exc.reason}") from exc

    def generate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_store_description: str,
        available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        messages = build_generate_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            user_store_description=user_store_description,
            available_theme_templates=available_theme_templates,
        )
        return self._call_chat_completions(messages)

    def clarify_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        current_draft: Mapping[str, Any],
        prompt: str,
        context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        messages = build_clarify_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            current_draft=current_draft,
            prompt=prompt,
            context=context,
        )
        return self._call_chat_completions(messages)

    def regenerate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        original_store_description: str,
        current_draft: Mapping[str, Any],
        clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
        available_theme_templates: Sequence[str] | None = None,
    ) -> ProviderRawResponse:
        messages = build_regenerate_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            original_store_description=original_store_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
        )
        return self._call_chat_completions(messages)

    def regenerate_store_draft_section(
        self,
        *,
        tenant_id: int,
        store_id: int,
        target_section: str,
        original_store_description: str,
        current_draft: Mapping[str, Any],
        clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
        available_theme_templates: Sequence[str] | None = None,
    ) -> ProviderRawResponse:
        messages = build_regenerate_store_draft_section_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            target_section=target_section,
            original_store_description=original_store_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
        )
        return self._call_chat_completions(messages)


class OllamaProviderClient(AIProviderContract):
    API_URL = "http://localhost:11434/api/chat"

    def __init__(self) -> None:
        self.model_name = settings.AI_MODEL_NAME
        self.timeout = settings.AI_TIMEOUT
        self.api_url = getattr(settings, "AI_API_URL", self.API_URL)

    def _build_chat_payload(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                # Lower temperature to improve JSON compliance on small local models.
                "temperature": 0,
            },
        }

    @staticmethod
    def _normalize_to_chat_completions_shape(raw_response: Mapping[str, Any]) -> ProviderRawResponse:
        # If caller points to Ollama OpenAI-compatible endpoint, keep as-is.
        choices = raw_response.get("choices")
        if isinstance(choices, list) and choices:
            return dict(raw_response)

        # Native /api/chat shape.
        message = raw_response.get("message")
        if isinstance(message, Mapping) and "content" in message:
            return {
                "choices": [
                    {
                        "message": {
                            "content": message.get("content"),
                        }
                    }
                ]
            }

        # Defensive support for /api/generate-like shape.
        if "response" in raw_response:
            return {
                "choices": [
                    {
                        "message": {
                            "content": raw_response.get("response"),
                        }
                    }
                ]
            }

        raise RuntimeError("Ollama response format is unsupported or missing message content.")

    def _call_chat(self, messages: list[dict[str, str]]) -> ProviderRawResponse:
        payload = self._build_chat_payload(messages)
        try:
            raw_response = _post_json_request(
                url=self.api_url,
                payload=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            return self._normalize_to_chat_completions_shape(raw_response)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Provider HTTP error {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Provider connection error: {exc.reason}") from exc

    def generate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_store_description: str,
        available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        messages = build_generate_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            user_store_description=user_store_description,
            available_theme_templates=available_theme_templates,
        )
        return self._call_chat(messages)

    def clarify_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        current_draft: Mapping[str, Any],
        prompt: str,
        context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        messages = build_clarify_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            current_draft=current_draft,
            prompt=prompt,
            context=context,
        )
        return self._call_chat(messages)

    def regenerate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        original_store_description: str,
        current_draft: Mapping[str, Any],
        clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
        available_theme_templates: Sequence[str] | None = None,
    ) -> ProviderRawResponse:
        messages = build_regenerate_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            original_store_description=original_store_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
        )
        return self._call_chat(messages)

    def regenerate_store_draft_section(
        self,
        *,
        tenant_id: int,
        store_id: int,
        target_section: str,
        original_store_description: str,
        current_draft: Mapping[str, Any],
        clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
        available_theme_templates: Sequence[str] | None = None,
    ) -> ProviderRawResponse:
        messages = build_regenerate_store_draft_section_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            target_section=target_section,
            original_store_description=original_store_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
        )
        return self._call_chat(messages)


def get_ai_provider_client() -> AIProviderContract:
    provider_name = str(getattr(settings, "AI_PROVIDER", "openai")).strip().lower()
    if provider_name == "ollama":
        return OllamaProviderClient()
    if provider_name != "openai":
        raise ImproperlyConfigured(
            "Unsupported AI_PROVIDER value. Supported values: 'openai', 'ollama'."
        )
    return OpenAIProviderClient()
