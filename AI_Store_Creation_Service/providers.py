from __future__ import annotations
from abc import ABC, abstractmethod
import json
import os
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
    headers: Mapping[str, str],
    timeout: int,
) -> ProviderRawResponse:
    request = Request(
        url=url,
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )

    with urlopen(request, timeout=timeout) as response:
        response_body = response.read().decode("utf-8")
        return json.loads(response_body)


class OllamaProviderClient(AIProviderContract):
    API_URL = "https://ollama.com/api/chat"

    def __init__(self) -> None:
        self.api_key = (
            str(getattr(settings, "AI_API_KEY", "")).strip()
            or os.getenv("OLLAMA_API_KEY", "").strip()
        )
        self.model_name = (
            str(getattr(settings, "AI_MODEL_NAME", "")).strip()
            or "gpt-oss:120b"
        )
        self.timeout = int(getattr(settings, "AI_TIMEOUT", 60))
        self.temperature = float(getattr(settings, "AI_TEMPERATURE", 0.2))

        configured_api_url = str(getattr(settings, "AI_API_URL", "")).strip()
        self.api_url = configured_api_url or self.API_URL

    def _build_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ImproperlyConfigured(
                "AI_API_KEY or OLLAMA_API_KEY is required for Ollama Cloud."
            )

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_chat_payload(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature,
            },
        }

    @staticmethod
    def _normalize_to_chat_completions_shape(
        raw_response: Mapping[str, Any],
    ) -> ProviderRawResponse:
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

        choices = raw_response.get("choices")
        if isinstance(choices, list) and choices:
            return dict(raw_response)

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
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            return self._normalize_to_chat_completions_shape(raw_response)

        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP error {exc.code}: {error_body}") from exc

        except URLError as exc:
            raise RuntimeError(f"Ollama connection error: {exc.reason}") from exc

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
    provider_name = str(getattr(settings, "AI_PROVIDER", "ollama")).strip().lower()

    if provider_name != "ollama":
        raise ImproperlyConfigured(
            "AI_API_KEY or OLLAMA_API_KEY is required for Ollama Cloud."
        )

    return OllamaProviderClient()
