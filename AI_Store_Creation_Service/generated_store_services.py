"""Read service for the fully applied AI-generated store."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Model

from products.models import Inventory, ProductImage

from .selectors import (
    get_store_categories_for_ai_flow,
    get_store_for_ai_flow,
    get_store_products_for_ai_flow,
    get_store_settings_for_ai_flow,
    get_store_theme_config_for_ai_flow,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _model_payload(instance: Model | None) -> dict[str, Any] | None:
    if instance is None:
        return None

    payload: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        key = field.name
        value = getattr(instance, field.attname)
        payload[key] = _json_value(value)
    return payload


def get_applied_ai_store_details(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """Return all persisted data produced by Apply Store for one owned store."""
    store = get_store_for_ai_flow(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    if store is None:
        raise ValidationError("Store not found or access denied")

    settings = get_store_settings_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=tenant_id,
    )
    theme = get_store_theme_config_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=tenant_id,
    )
    categories = list(
        get_store_categories_for_ai_flow(
            store_id=store.id,
            user=user,
            tenant_id=tenant_id,
        )
    )
    products = list(
        get_store_products_for_ai_flow(
            store_id=store.id,
            user=user,
            tenant_id=tenant_id,
        )
    )

    product_ids = [product.id for product in products]
    inventory_by_product_id = {
        row.product_id: row
        for row in Inventory.objects.filter(product_id__in=product_ids)
    }
    images_by_product_id: dict[int, list[dict[str, Any]]] = {}
    for image in ProductImage.objects.filter(product_id__in=product_ids).order_by("id"):
        images_by_product_id.setdefault(image.product_id, []).append(
            _model_payload(image) or {}
        )

    category_payloads = [_model_payload(category) or {} for category in categories]
    product_payloads: list[dict[str, Any]] = []
    for product in products:
        product_payload = _model_payload(product) or {}
        product_payload["category"] = (
            {
                "id": product.category_id,
                "name": getattr(product.category, "name", None),
            }
            if product.category_id
            else None
        )
        product_payload["inventory"] = _model_payload(
            inventory_by_product_id.get(product.id)
        )
        product_payload["images"] = images_by_product_id.get(product.id, [])
        product_payloads.append(product_payload)

    theme_payload = _model_payload(theme)
    if theme_payload is not None and getattr(theme, "theme_template", None) is not None:
        theme_payload["theme_template"] = {
            "id": theme.theme_template_id,
            "name": theme.theme_template.name,
        }

    return {
        "store_id": store.id,
        "store": _model_payload(store),
        "settings": _model_payload(settings),
        "theme": theme_payload,
        "categories_count": len(category_payloads),
        "categories": category_payloads,
        "products_count": len(product_payloads),
        "products": product_payloads,
    }
