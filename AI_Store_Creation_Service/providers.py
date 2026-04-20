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
    """
    Official provider interface for AI Store Creation workflow.

    Contract decision:
    Implementations return raw provider response payloads.
    Parsing/normalization to workflow schema is handled in later layers.

    The workflow is store-anchored; the same store_id is reused across calls.
    """

    @abstractmethod
    def generate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_store_description: str,
        available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        """
        Execute provider call for initial draft generation.
        Returns raw provider response.
        """
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
        """
        Execute provider call for clarification pass.
        Returns raw provider response.
        """
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
        """
        Execute provider call for regeneration pass.
        Returns raw provider response.
        """
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
        """
        Execute provider call for partial section regeneration.
        Returns raw provider response.
        """
        raise NotImplementedError


class OpenAIProviderClient(AIProviderContract):
    """
    Concrete provider client for OpenAI Chat Completions API.

    This class is intentionally limited to provider communication only.
    """

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
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        } | (
            {"HTTP-Referer": self.http_referer.strip()} if self.http_referer else {}
        ) | (
            {"X-Title": self.app_title.strip()} if self.app_title else {}
        )

    def _call_chat_completions(self, messages: list[dict[str, str]]) -> ProviderRawResponse:
        payload = {
            "model": self.model_name,
            "messages": messages,
            # Request JSON-shaped answer from provider; domain parsing remains outside this layer.
            "response_format": {"type": "json_object"},
        }

        request = Request(
            url=self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._build_headers(),
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Provider HTTP error {exc.code}: {error_body}"
            ) from exc
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
        """
        Execute official generation flow using description + available templates.

        `store_id` remains part of the contract for workflow anchoring.
        """
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
        """
        Execute official full-regeneration flow.

        Uses original description + current draft + optional clarification context
        and optional available template names.
        """
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
        """
        Execute official partial-regeneration flow for one target section.
        """
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


def get_ai_provider_client() -> AIProviderContract:
    """
    Return the default configured AI provider client.
    """
    return OpenAIProviderClient()
