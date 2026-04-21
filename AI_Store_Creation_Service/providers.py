# """
# AI provider contract layer.

# This module defines the official abstraction for provider communication and
# request execution. Prompt/message construction belongs to prompts.py.
# """

# from __future__ import annotations

# from abc import ABC, abstractmethod
# import json
# from typing import Any, Mapping, Sequence
# from urllib.error import HTTPError, URLError
# from urllib.request import Request, urlopen

# from django.conf import settings
# from django.core.exceptions import ImproperlyConfigured

# from .prompts import (
#     build_generate_store_draft_messages,
#     build_clarify_store_draft_messages,
#     build_regenerate_store_draft_messages,
#     build_regenerate_store_draft_section_messages,
# )


# ProviderRawResponse = dict[str, Any]


# class AIProviderContract(ABC):
#     @abstractmethod
#     def generate_store_draft(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         user_store_description: str,
#         available_theme_templates: Sequence[str],
#     ) -> ProviderRawResponse:
#         raise NotImplementedError

#     @abstractmethod
#     def clarify_store_draft(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         current_draft: Mapping[str, Any],
#         prompt: str,
#         context: Mapping[str, Any] | None = None,
#     ) -> ProviderRawResponse:
#         raise NotImplementedError

#     @abstractmethod
#     def regenerate_store_draft(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         original_store_description: str,
#         current_draft: Mapping[str, Any],
#         clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
#         available_theme_templates: Sequence[str] | None = None,
#     ) -> ProviderRawResponse:
#         raise NotImplementedError

#     @abstractmethod
#     def regenerate_store_draft_section(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         target_section: str,
#         original_store_description: str,
#         current_draft: Mapping[str, Any],
#         clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
#         available_theme_templates: Sequence[str] | None = None,
#     ) -> ProviderRawResponse:
#         raise NotImplementedError


# class OpenAIProviderClient(AIProviderContract):
#     API_URL = "https://api.openai.com/v1/chat/completions"

#     def __init__(self) -> None:
#         self.api_key = settings.AI_API_KEY
#         self.model_name = settings.AI_MODEL_NAME
#         self.timeout = settings.AI_TIMEOUT
#         self.api_url = getattr(settings, "AI_API_URL", self.API_URL)
#         self.http_referer = getattr(settings, "AI_HTTP_REFERER", "")
#         self.app_title = getattr(settings, "AI_APP_TITLE", "")

#     def _build_headers(self) -> dict[str, str]:
#         if not self.api_key:
#             raise ImproperlyConfigured(
#                 "AI_API_KEY is not configured. Set it in environment/.env before calling provider."
#             )

#         headers = {
#             "Authorization": f"Bearer {self.api_key}",
#             "Content-Type": "application/json",
#         }

#         if self.http_referer:
#             headers["HTTP-Referer"] = self.http_referer.strip()

#         if self.app_title:
#             headers["X-Title"] = self.app_title.strip()

#         return headers

#     def _build_chat_payload(
#         self,
#         messages: list[dict[str, str]],
#         *,
#         include_response_format: bool,
#     ) -> dict[str, Any]:
#         payload: dict[str, Any] = {
#             "model": self.model_name,
#             "messages": messages,
#             "provider": {
#                 "require_parameters": True,
#             },
#             "plugins": [
#                 {"id": "response-healing"},
#             ],
#             "temperature": 0.2,
#         }

#         if include_response_format:
#             # Keep this for models/providers that support JSON object output.
#             # The caller already retries without it if unsupported.
#             payload["response_format"] = {"type": "json_object"}

#         return payload

#     @staticmethod
#     def _is_response_format_unsupported_error(status_code: int, error_body: str) -> bool:
#         if status_code not in {400, 404, 422}:
#             return False

#         normalized = (error_body or "").lower()
#         indicators = (
#             "response_format",
#             "json_object",
#             "unsupported parameter",
#             "not supported",
#             "unknown parameter",
#             "invalid parameter",
#         )
#         return any(marker in normalized for marker in indicators)

#     def _send_chat_completions_request(self, payload: Mapping[str, Any]) -> ProviderRawResponse:
#         request = Request(
#             url=self.api_url,
#             data=json.dumps(dict(payload)).encode("utf-8"),
#             headers=self._build_headers(),
#             method="POST",
#         )

#         with urlopen(request, timeout=self.timeout) as response:
#             response_body = response.read().decode("utf-8")
#             return json.loads(response_body)

#     def _call_chat_completions(self, messages: list[dict[str, str]]) -> ProviderRawResponse:
#         payload = self._build_chat_payload(messages, include_response_format=True)

#         try:
#             return self._send_chat_completions_request(payload)
#         except HTTPError as exc:
#             error_body = exc.read().decode("utf-8", errors="replace")

#             if self._is_response_format_unsupported_error(exc.code, error_body):
#                 retry_payload = self._build_chat_payload(
#                     messages,
#                     include_response_format=False,
#                 )
#                 try:
#                     return self._send_chat_completions_request(retry_payload)
#                 except HTTPError as retry_exc:
#                     retry_error_body = retry_exc.read().decode("utf-8", errors="replace")
#                     raise RuntimeError(
#                         f"Provider HTTP error {retry_exc.code}: {retry_error_body}"
#                     ) from retry_exc
#                 except URLError as retry_exc:
#                     raise RuntimeError(
#                         f"Provider connection error: {retry_exc.reason}"
#                     ) from retry_exc

#             raise RuntimeError(f"Provider HTTP error {exc.code}: {error_body}") from exc
#         except URLError as exc:
#             raise RuntimeError(f"Provider connection error: {exc.reason}") from exc

#     def generate_store_draft(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         user_store_description: str,
#         available_theme_templates: Sequence[str],
#     ) -> ProviderRawResponse:
#         messages = build_generate_store_draft_messages(
#             tenant_id=tenant_id,
#             store_id=store_id,
#             user_store_description=user_store_description,
#             available_theme_templates=available_theme_templates,
#         )
#         return self._call_chat_completions(messages)

#     def clarify_store_draft(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         current_draft: Mapping[str, Any],
#         prompt: str,
#         context: Mapping[str, Any] | None = None,
#     ) -> ProviderRawResponse:
#         messages = build_clarify_store_draft_messages(
#             tenant_id=tenant_id,
#             store_id=store_id,
#             current_draft=current_draft,
#             prompt=prompt,
#             context=context,
#         )
#         return self._call_chat_completions(messages)

#     def regenerate_store_draft(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         original_store_description: str,
#         current_draft: Mapping[str, Any],
#         clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
#         available_theme_templates: Sequence[str] | None = None,
#     ) -> ProviderRawResponse:
#         messages = build_regenerate_store_draft_messages(
#             tenant_id=tenant_id,
#             store_id=store_id,
#             original_store_description=original_store_description,
#             current_draft=current_draft,
#             clarification_context=clarification_context,
#             available_theme_templates=available_theme_templates,
#         )
#         return self._call_chat_completions(messages)

#     def regenerate_store_draft_section(
#         self,
#         *,
#         tenant_id: int,
#         store_id: int,
#         target_section: str,
#         original_store_description: str,
#         current_draft: Mapping[str, Any],
#         clarification_context: Mapping[str, Any] | Sequence[Any] | None = None,
#         available_theme_templates: Sequence[str] | None = None,
#     ) -> ProviderRawResponse:
#         messages = build_regenerate_store_draft_section_messages(
#             tenant_id=tenant_id,
#             store_id=store_id,
#             target_section=target_section,
#             original_store_description=original_store_description,
#             current_draft=current_draft,
#             clarification_context=clarification_context,
#             available_theme_templates=available_theme_templates,
#         )
#         return self._call_chat_completions(messages)


# def get_ai_provider_client() -> AIProviderContract:
#     return OpenAIProviderClient()




from __future__ import annotations

import json
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ValidationError


class OpenRouterClient:
    """
    Minimal OpenRouter-compatible provider client for the AI store workflow.

    Important contract:
    - Service layer expects provider methods to return the RAW provider response dict
      (not extracted text content), because parsing is handled later by:
        parse_provider_raw_response_to_dict(raw_response)
    - Therefore each method here returns response.json()
    """

    def __init__(self) -> None:
        self.api_key = (getattr(settings, "AI_API_KEY", "") or "").strip()
        self.model_name = (getattr(settings, "AI_MODEL_NAME", "") or "").strip()
        self.api_url = (getattr(settings, "AI_API_URL", "") or "").strip()
        self.timeout = int(getattr(settings, "AI_TIMEOUT", 120) or 120)
        self.http_referer = (getattr(settings, "AI_HTTP_REFERER", "") or "").strip()
        self.app_title = (getattr(settings, "AI_APP_TITLE", "") or "").strip()

        if not self.api_key:
            raise ValidationError(
                "AI_API_KEY is not configured. Set it in environment/.env before calling provider."
            )
        if not self.model_name:
            raise ValidationError("AI_MODEL_NAME is not configured.")
        if not self.api_url:
            raise ValidationError("AI_API_URL is not configured.")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Recommended by OpenRouter
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.app_title:
            headers["X-Title"] = self.app_title

        return headers

    def _post_chat(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.4,
        }

        response = requests.post(
            self.api_url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )

        # Useful for local debugging only
        print("STATUS:", response.status_code)
        print("RESPONSE:", response.text)

        response.raise_for_status()
        return response.json()

    @staticmethod
    def _json_block(title: str, data: Any) -> str:
        return f"{title}:\n{json.dumps(data, ensure_ascii=False, indent=2)}"

    def generate_store_draft(
        self,
        tenant_id: int,
        store_id: int,
        user_store_description: str,
        available_theme_templates: list[str],
    ) -> dict[str, Any]:
        system_prompt = (
            "You are an AI assistant for an e-commerce multi-tenant SaaS backend.\n"
            "Return ONLY valid JSON with no markdown and no extra commentary.\n"
            "You must return one of two modes:\n"
            "1) draft_ready:\n"
            "{\n"
            '  "store": {"name": "...", "description": "..."},\n'
            '  "store_settings": {"currency": "USD", "language": "en", "timezone": "UTC"},\n'
            '  "theme": {\n'
            '    "theme_template": "...",\n'
            '    "primary_color": "#112233",\n'
            '    "secondary_color": "rgb(255, 255, 255)",\n'
            '    "font_family": "Inter",\n'
            '    "logo_url": "",\n'
            '    "banner_url": ""\n'
            "  },\n"
            '  "categories": [{"name": "..."}],\n'
            '  "products": [\n'
            "    {\n"
            '      "name": "...",\n'
            '      "description": "...",\n'
            '      "price": 25.5,\n'
            '      "sku": "SKU-001",\n'
            '      "category_name": "...",\n'
            '      "stock_quantity": 5,\n'
            '      "image_url": ""\n'
            "    }\n"
            "  ],\n"
            '  "clarification_needed": false,\n'
            '  "clarification_questions": []\n'
            "}\n\n"
            "2) clarification mode:\n"
            "{\n"
            '  "store": {},\n'
            '  "store_settings": {},\n'
            '  "theme": {},\n'
            '  "categories": [],\n'
            '  "products": [],\n'
            '  "clarification_needed": true,\n'
            '  "clarification_questions": [\n'
            "    {\n"
            '      "question_key": "store_type",\n'
            '      "question_text": "What type of store is this?",\n'
            '      "options": ["Fashion", "Electronics", "Beauty"]\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- theme.theme_template MUST exactly match one of the allowed theme template names.\n"
            "- categories[].name must be simple store categories.\n"
            "- each product.category_name must match one category name exactly.\n"
            "- Return JSON only."
        )

        user_prompt = (
            f"Generate an initial store draft.\n"
            f"tenant_id: {tenant_id}\n"
            f"store_id: {store_id}\n"
            f"user_store_description: {user_store_description}\n"
            f"available_theme_templates: {json.dumps(available_theme_templates, ensure_ascii=False)}"
        )

        return self._post_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def clarify_store_draft(
        self,
        tenant_id: int,
        store_id: int,
        current_draft: dict[str, Any],
        prompt: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = (
            "You are continuing an AI store draft clarification workflow.\n"
            "Return ONLY valid JSON with no markdown.\n"
            "If enough information is now available, return full draft_ready JSON.\n"
            "Otherwise return clarification JSON with new clarification_questions.\n"
            "Preserve the same response schema as the initial draft workflow."
        )

        user_prompt = "\n\n".join(
            [
                f"Continue clarification for tenant_id={tenant_id}, store_id={store_id}.",
                self._json_block("Current draft", current_draft),
                self._json_block("Clarification context", context),
                f"Latest clarification input:\n{prompt}",
            ]
        )

        return self._post_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def regenerate_store_draft(
        self,
        tenant_id: int,
        store_id: int,
        original_store_description: str,
        current_draft: dict[str, Any],
        clarification_context: dict[str, Any],
        available_theme_templates: list[str],
    ) -> dict[str, Any]:
        system_prompt = (
            "You are regenerating a full AI store draft.\n"
            "Return ONLY valid JSON.\n"
            "Use the original store description, current draft, and clarification context.\n"
            "If enough information exists, return full draft_ready JSON.\n"
            "Otherwise return clarification JSON.\n"
            "theme.theme_template MUST exactly match one of the allowed theme template names."
        )

        user_prompt = "\n\n".join(
            [
                f"Regenerate full draft for tenant_id={tenant_id}, store_id={store_id}.",
                f"Original store description:\n{original_store_description}",
                self._json_block("Current draft", current_draft),
                self._json_block("Clarification context", clarification_context),
                f"Available theme templates:\n{json.dumps(available_theme_templates, ensure_ascii=False, indent=2)}",
            ]
        )

        return self._post_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def regenerate_store_draft_section(
        self,
        tenant_id: int,
        store_id: int,
        target_section: str,
        original_store_description: str,
        current_draft: dict[str, Any],
        clarification_context: dict[str, Any],
        available_theme_templates: list[str] | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are regenerating ONLY ONE section of an AI store draft.\n"
            "Return ONLY valid JSON with exactly one top-level key matching the requested target section.\n"
            "Allowed target sections: theme, categories, products.\n"
            "Examples:\n"
            '- If target_section="theme", return: {"theme": {...}}\n'
            '- If target_section="categories", return: {"categories": [...]} \n'
            '- If target_section="products", return: {"products": [...]} \n'
            "Do not return the full draft.\n"
            "For theme regeneration, theme.theme_template MUST exactly match one allowed template name."
        )

        blocks = [
            f"Regenerate section for tenant_id={tenant_id}, store_id={store_id}.",
            f"target_section: {target_section}",
            f"Original store description:\n{original_store_description}",
            self._json_block("Current draft", current_draft),
            self._json_block("Clarification context", clarification_context),
        ]

        if available_theme_templates is not None:
            blocks.append(
                f"Available theme templates:\n"
                f"{json.dumps(available_theme_templates, ensure_ascii=False, indent=2)}"
            )

        user_prompt = "\n\n".join(blocks)

        return self._post_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )


def get_ai_provider_client() -> OpenRouterClient:
    return OpenRouterClient()