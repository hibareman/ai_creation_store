"""
Prompt/message builders for AI Store Creation provider calls.

This module is responsible only for constructing provider message payloads.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


ProviderMessage = dict[str, str]


def build_generate_store_draft_messages(
    *,
    store_id: int,
    prompt: str,
    context: Mapping[str, Any] | None = None,
) -> list[ProviderMessage]:
    messages: list[ProviderMessage] = [
        {
            "role": "system",
            "content": "You generate store setup drafts. Return only valid JSON.",
        },
        {"role": "user", "content": prompt},
        {"role": "user", "content": f"store_id: {store_id}"},
    ]
    if context:
        messages.append(
            {
                "role": "user",
                "content": f"context: {json.dumps(dict(context), ensure_ascii=False)}",
            }
        )
    return messages


def build_clarify_store_draft_messages(
    *,
    store_id: int,
    current_draft: Mapping[str, Any],
    prompt: str,
    context: Mapping[str, Any] | None = None,
) -> list[ProviderMessage]:
    messages: list[ProviderMessage] = [
        {
            "role": "system",
            "content": "You refine an existing store draft. Return only valid JSON.",
        },
        {"role": "user", "content": prompt},
        {"role": "user", "content": f"store_id: {store_id}"},
        {
            "role": "user",
            "content": f"current_draft: {json.dumps(dict(current_draft), ensure_ascii=False)}",
        },
    ]
    if context:
        messages.append(
            {
                "role": "user",
                "content": f"context: {json.dumps(dict(context), ensure_ascii=False)}",
            }
        )
    return messages


def build_regenerate_store_draft_messages(
    *,
    store_id: int,
    current_draft: Mapping[str, Any] | None = None,
    prompt: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> list[ProviderMessage]:
    messages: list[ProviderMessage] = [
        {
            "role": "system",
            "content": "You regenerate a store draft. Return only valid JSON.",
        },
        {
            "role": "user",
            "content": prompt or "Regenerate the store draft with improved output quality.",
        },
        {"role": "user", "content": f"store_id: {store_id}"},
    ]
    if current_draft:
        messages.append(
            {
                "role": "user",
                "content": f"current_draft: {json.dumps(dict(current_draft), ensure_ascii=False)}",
            }
        )
    if context:
        messages.append(
            {
                "role": "user",
                "content": f"context: {json.dumps(dict(context), ensure_ascii=False)}",
            }
        )
    return messages
