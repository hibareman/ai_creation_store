from __future__ import annotations
from abc import ABC, abstractmethod
from decimal import Decimal
import json
import logging
import os
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from .prompts import (
    build_analyze_store_description_messages,
    build_generate_store_blueprint_messages,
    build_repair_store_blueprint_messages,
    build_generate_agentic_store_draft_messages,
    build_generate_clarification_questions_messages,
    build_generate_store_draft_messages,
    build_clarify_store_draft_messages,
    build_regenerate_store_draft_messages,
    build_regenerate_store_draft_section_messages,
)
from .product_description_prompts import (
    PRODUCT_DESCRIPTION_OUTPUT_SCHEMA,
    build_product_description_messages,
)


ProviderRawResponse = dict[str, Any]
logger = logging.getLogger(__name__)


def _terminal_json(value: Any) -> str:
    """Render provider diagnostics without changing request/response behavior."""

    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return repr(value)



class AIProviderContract(ABC):
    @abstractmethod
    def analyze_store_description(
        self,
        *,
        tenant_id: int,
        store_id: int,
        normalized_description: str,
        clarification_context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        raise NotImplementedError

    @abstractmethod
    def generate_clarification_questions(
        self,
        *,
        tenant_id: int,
        store_id: int,
        normalized_description: str,
        semantic_analysis: Mapping[str, Any],
        clarification_round_count: int,
        clarification_context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        raise NotImplementedError

    def generate_store_blueprint(
        self, *, tenant_id: int, store_id: int, normalized_description: str,
        effective_personalization_context: Mapping[str, Any],
        clarification_history: Sequence[Any], available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        raise NotImplementedError

    def repair_store_blueprint(
        self, *, tenant_id: int, store_id: int, invalid_blueprint: Mapping[str, Any],
        validation_errors: Sequence[Mapping[str, Any]],
        effective_personalization_context: Mapping[str, Any],
        available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        raise NotImplementedError

    @abstractmethod
    def generate_product_description(
        self,
        *,
        mode: str,
        product_name: str,
        category_name: str,
        price: Decimal | int | float | str,
        current_description: str = "",
        additional_information: str = "",
        detected_language: str,
    ) -> ProviderRawResponse:
        """Generate or improve a product description without persisting data."""
        raise NotImplementedError

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
    def generate_agentic_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_store_description: str,
        available_theme_templates: Sequence[str],
        blueprint: Mapping[str, Any] | None = None,
        effective_personalization_context: Mapping[str, Any] | None = None,
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
        blueprint: Mapping[str, Any] | None = None,
        confirmed_personalization_context: Mapping[str, Any] | None = None,
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
        blueprint: Mapping[str, Any] | None = None,
        confirmed_personalization_context: Mapping[str, Any] | None = None,
        user_instruction: str | None = None,
        validation_feedback: str | None = None,
        attempt_number: int = 1,
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
        self.max_tokens = int(getattr(settings, "AI_MAX_TOKENS", 4096))
        self.temperature = float(getattr(settings, "AI_TEMPERATURE", 0.2))
        self.product_description_temperature = float(
            getattr(settings, "AI_PRODUCT_DESCRIPTION_TEMPERATURE", 0.0)
        )

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

    def _supports_json_schema_format(self) -> bool:
        """Return whether this Ollama endpoint can accept a schema in ``format``.

        Ollama's local API supports JSON Schema structured outputs. Ollama Cloud
        currently accepts JSON mode but not schema objects, so cloud requests
        retain ``format="json"`` while the same schema remains embedded in the
        product-description prompt and is validated again by the backend.
        """

        hostname = (urlparse(self.api_url).hostname or "").strip().lower()
        return hostname not in {"ollama.com", "www.ollama.com"}

    def _build_chat_payload(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: Mapping[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        effective_temperature = (
            self.temperature if temperature is None else float(temperature)
        )
        response_format: str | dict[str, Any] = "json"
        if response_schema is not None and self._supports_json_schema_format():
            response_format = dict(response_schema)

        return {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": response_format,
            "options": {
                "temperature": effective_temperature,
                "num_predict": self.max_tokens,
                "top_p": 0.9,
                "repeat_penalty": 1.05,
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

    def _call_chat(
        self,
        messages: list[dict[str, str]],
        *,
        operation: str = "chat",
        response_schema: Mapping[str, Any] | None = None,
        temperature: float | None = None,
    ) -> ProviderRawResponse:
        payload = self._build_chat_payload(
            messages,
            response_schema=response_schema,
            temperature=temperature,
        )

        logger.warning(
            "AI PROVIDER CALL START | operation=%s | model=%s | endpoint=%s",
            operation,
            self.model_name,
            self.api_url,
        )

        try:
            raw_response = _post_json_request(
                url=self.api_url,
                payload=payload,
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            logger.warning(
                "AI RAW RESPONSE | operation=%s | response=%s",
                operation,
                _terminal_json(raw_response),
            )

            normalized_response = self._normalize_to_chat_completions_shape(
                raw_response
            )
            logger.warning(
                "AI NORMALIZED RESPONSE | operation=%s | response=%s",
                operation,
                _terminal_json(normalized_response),
            )
            return normalized_response

        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.exception(
                "AI PROVIDER HTTP FAILURE | operation=%s | status=%s | body=%s",
                operation,
                exc.code,
                error_body,
            )
            raise RuntimeError(f"Ollama HTTP error {exc.code}: {error_body}") from exc

        except URLError as exc:
            logger.exception(
                "AI PROVIDER CONNECTION FAILURE | operation=%s | reason=%r",
                operation,
                exc.reason,
            )
            raise RuntimeError(f"Ollama connection error: {exc.reason}") from exc

        except Exception as exc:
            logger.exception(
                "AI PROVIDER RESPONSE FAILURE | operation=%s | "
                "error_type=%s | error=%r",
                operation,
                type(exc).__name__,
                exc,
            )
            raise


    def analyze_store_description(
        self,
        *,
        tenant_id: int,
        store_id: int,
        normalized_description: str,
        clarification_context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        messages = build_analyze_store_description_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            normalized_description=normalized_description,
            clarification_context=clarification_context,
        )
        return self._call_chat(messages, operation="analyze_store_description")

    def generate_store_blueprint(
        self, *, tenant_id: int, store_id: int, normalized_description: str,
        effective_personalization_context: Mapping[str, Any],
        clarification_history: Sequence[Any], available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        return self._call_chat(
            build_generate_store_blueprint_messages(
                tenant_id=tenant_id, store_id=store_id, normalized_description=normalized_description,
                effective_personalization_context=effective_personalization_context,
                clarification_history=clarification_history,
                available_theme_templates=available_theme_templates,
            ),
            operation="generate_store_blueprint",
        )

    def repair_store_blueprint(
        self, *, tenant_id: int, store_id: int, invalid_blueprint: Mapping[str, Any],
        validation_errors: Sequence[Mapping[str, Any]],
        effective_personalization_context: Mapping[str, Any],
        available_theme_templates: Sequence[str],
    ) -> ProviderRawResponse:
        return self._call_chat(
            build_repair_store_blueprint_messages(
                tenant_id=tenant_id, store_id=store_id, invalid_blueprint=invalid_blueprint,
                validation_errors=validation_errors,
                effective_personalization_context=effective_personalization_context,
                available_theme_templates=available_theme_templates,
            ),
            operation="repair_store_blueprint",
        )

    def generate_product_description(
        self,
        *,
        mode: str,
        product_name: str,
        category_name: str,
        price: Decimal | int | float | str,
        current_description: str = "",
        additional_information: str = "",
        detected_language: str,
    ) -> ProviderRawResponse:
        """Call Ollama for the AI product-description feature.

        Product data is converted to provider messages by the dedicated prompt
        builder. The request uses a task-specific deterministic temperature and
        applies the response schema whenever the configured Ollama endpoint
        supports schema-formatted structured outputs.
        """

        messages = build_product_description_messages(
            mode=mode,
            product_name=product_name,
            category_name=category_name,
            price=price,
            current_description=current_description,
            additional_information=additional_information,
            detected_language=detected_language,
        )
        return self._call_chat(
            messages,
            operation="generate_product_description",
            response_schema=PRODUCT_DESCRIPTION_OUTPUT_SCHEMA,
            temperature=self.product_description_temperature,
        )

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
        return self._call_chat(messages, operation="generate_store_draft")

    def generate_agentic_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        user_store_description: str,
        available_theme_templates: Sequence[str],
        blueprint: Mapping[str, Any] | None = None,
        effective_personalization_context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        messages = build_generate_agentic_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            user_store_description=user_store_description,
            available_theme_templates=available_theme_templates,
            blueprint=blueprint,
            effective_personalization_context=effective_personalization_context,
        )
        return self._call_chat(messages, operation="generate_agentic_store_draft")

    def generate_clarification_questions(
        self,
        *,
        tenant_id: int,
        store_id: int,
        normalized_description: str,
        semantic_analysis: Mapping[str, Any],
        clarification_round_count: int,
        clarification_context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        messages = build_generate_clarification_questions_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            normalized_description=normalized_description,
            semantic_analysis=semantic_analysis,
            clarification_round_count=clarification_round_count,
            clarification_context=clarification_context,
        )
        return self._call_chat(messages, operation="generate_clarification_questions")

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
        return self._call_chat(messages, operation="clarify_store_draft")

    def regenerate_store_draft(
        self,
        *,
        tenant_id: int,
        store_id: int,
        original_store_description: str,
        current_draft: Mapping[str, Any],
        clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
        available_theme_templates: Sequence[str] | None = None,
        blueprint: Mapping[str, Any] | None = None,
        confirmed_personalization_context: Mapping[str, Any] | None = None,
    ) -> ProviderRawResponse:
        messages = build_regenerate_store_draft_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            original_store_description=original_store_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
            blueprint=blueprint,
            confirmed_personalization_context=confirmed_personalization_context,
        )
        return self._call_chat(messages, operation="regenerate_store_draft")

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
        user_instruction: str | None = None,
        validation_feedback: str | None = None,
        attempt_number: int = 1,
    ) -> ProviderRawResponse:
        messages = build_regenerate_store_draft_section_messages(
            tenant_id=tenant_id,
            store_id=store_id,
            target_section=target_section,
            original_store_description=original_store_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
            user_instruction=user_instruction,
            validation_feedback=validation_feedback,
            attempt_number=attempt_number,
        )
        return self._call_chat(messages, operation="regenerate_store_draft_section")


def get_ai_provider_client() -> AIProviderContract:
    provider_name = str(getattr(settings, "AI_PROVIDER", "ollama")).strip().lower()

    if provider_name != "ollama":
        raise ImproperlyConfigured(
            "AI_API_KEY or OLLAMA_API_KEY is required for Ollama Cloud."
        )

    return OllamaProviderClient()
