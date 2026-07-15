"""
Final draft application services for AI Store Creation.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from categories.models import Category
from products.models import Inventory, Product, ProductImage
from stores.models import StoreSettings
from themes.models import StoreThemeConfig

from .audit_services import _write_ai_audit_log
from .constants import (
    CATEGORY_APPLY_FAILED_ERROR_CODE,
    CATEGORY_APPLY_FAILED_USER_MESSAGE,
    PRODUCT_APPLY_FAILED_ERROR_CODE,
    PRODUCT_APPLY_FAILED_USER_MESSAGE,
    READY_FOR_REVIEW_WORKFLOW_STATUSES,
    STORE_CORE_APPLY_FAILED_ERROR_CODE,
    STORE_CORE_APPLY_FAILED_USER_MESSAGE,
    WORKFLOW_STATUS_APPLIED,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)
from .draft_store import (
    delete_ai_draft,
    delete_ai_draft_meta,
    get_ai_draft,
    get_ai_draft_meta,
)
from .exceptions import AIDraftSchemaValidationError
from .metadata_services import _get_or_rebuild_draft_metadata
from .normalization import _ensure_theme_template_is_available
from .selectors import (
    get_available_theme_template_names,
    get_store_for_ai_flow,
    get_store_categories_for_ai_flow,
    get_store_products_for_ai_flow,
    get_store_settings_for_ai_flow,
    get_store_theme_config_for_ai_flow,
    get_theme_template_by_exact_name,
)
from .validators import (
    detect_ai_response_mode,
    validate_basic_draft_schema,
    validate_categories_section,
    validate_products_section,
    validate_store_section,
    validate_store_settings_section,
    validate_theme_section,
)


logger = logging.getLogger(__name__)


def _normalize_category_name_for_compare(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


def _normalize_category_name_for_store(name: str) -> str:
    return " ".join(name.strip().split())


def _normalize_sku_for_compare(sku: str) -> str:
    return " ".join(sku.strip().split()).casefold()


def _log_and_audit_apply_failure(
    *,
    action: str,
    error_code: str,
    store,
    user,
    tenant_id: int,
    exc: Exception,
) -> None:
    logger.warning(
        "AI draft apply operation failed. action=%s, error_code=%s, "
        "store_id=%s, tenant_id=%s, reason=%s",
        action,
        error_code,
        getattr(store, "id", None),
        tenant_id,
        str(exc),
    )
    _write_ai_audit_log(
        tenant_id=tenant_id,
        store_id=getattr(store, "id", None),
        actor_id=getattr(user, "id", None),
        action=action,
        status="failed",
        message=str(exc),
    )


def _technical_exception_reason(exc: Exception) -> str:
    root: BaseException = exc
    while getattr(root, "__cause__", None) is not None:
        root = root.__cause__
    return str(root)


def apply_current_ai_draft_store_core(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Apply current temporary AI draft to Store + StoreThemeConfig only.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = _get_or_rebuild_draft_metadata(
        store=store,
        draft_payload=current_draft,
        draft_meta=get_ai_draft_meta(store.id),
        rebuild_partial=True,
    )
    if draft_meta.get("status") not in READY_FOR_REVIEW_WORKFLOW_STATUSES:
        raise ValidationError("Current workflow state is not ready_for_review")

    try:
        current_draft = validate_basic_draft_schema(current_draft)
        mode = detect_ai_response_mode(current_draft)
        if mode != "draft_ready":
            raise AIDraftSchemaValidationError("Current draft payload is not draft_ready")

        store_section = validate_store_section(current_draft["store"])
        store_settings_data = validate_store_settings_section(current_draft["store_settings"])
        store_name = store_section["name"]
        store_description = store_section["description"]
        settings_currency = str(store_settings_data["currency"]).strip()
        settings_language = str(store_settings_data["language"]).strip()
        settings_timezone = str(store_settings_data["timezone"]).strip()

        theme_data = validate_theme_section(current_draft["theme"])
        validated_categories = validate_categories_section(current_draft["categories"])
        category_names = [item["name"] for item in validated_categories]
        validate_products_section(current_draft["products"], category_names)

        available_theme_templates = get_available_theme_template_names()
        if not available_theme_templates:
            raise AIDraftSchemaValidationError("No available theme templates found")
        _ensure_theme_template_is_available(theme_data, available_theme_templates)

        theme_template_name = str(theme_data["theme_template"]).strip()
        theme_template_obj = get_theme_template_by_exact_name(theme_template_name)
        if theme_template_obj is None:
            raise AIDraftSchemaValidationError(
                "Theme field 'theme_template' does not resolve to an existing ThemeTemplate."
            )
    except AIDraftSchemaValidationError as exc:
        raise ValidationError(str(exc)) from exc

    try:
        with transaction.atomic():
            store.name = store_name.strip()
            store.description = store_description
            store.save()

            store_settings = get_store_settings_for_ai_flow(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )
            if store_settings is None:
                store_settings = StoreSettings.objects.create(
                    store=store,
                    currency=settings_currency,
                    language=settings_language,
                    timezone=settings_timezone,
                )
            else:
                store_settings.currency = settings_currency
                store_settings.language = settings_language
                store_settings.timezone = settings_timezone
                store_settings.save(
                    update_fields=[
                        "currency",
                        "language",
                        "timezone",
                        "updated_at",
                    ]
                )

            store_theme_config = get_store_theme_config_for_ai_flow(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )
            if store_theme_config is None:
                store_theme_config = StoreThemeConfig.objects.create(
                    store=store,
                    theme_template=theme_template_obj,
                    primary_color=theme_data["primary_color"],
                    secondary_color=theme_data["secondary_color"],
                    font_family=theme_data["font_family"],
                    logo_url=theme_data["logo_url"],
                    banner_url=theme_data["banner_url"],
                )
            else:
                store_theme_config.theme_template = theme_template_obj
                store_theme_config.primary_color = theme_data["primary_color"]
                store_theme_config.secondary_color = theme_data["secondary_color"]
                store_theme_config.font_family = theme_data["font_family"]
                store_theme_config.logo_url = theme_data["logo_url"]
                store_theme_config.banner_url = theme_data["banner_url"]
                store_theme_config.save()
    except Exception as exc:
        _log_and_audit_apply_failure(
            action="apply_store_core",
            error_code=STORE_CORE_APPLY_FAILED_ERROR_CODE,
            store=store,
            user=user,
            tenant_id=normalized_tenant_id,
            exc=exc,
        )
        raise ValidationError(STORE_CORE_APPLY_FAILED_USER_MESSAGE) from exc

    return {
        "store_id": store.id,
        "draft_status": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "store": {
            "name": store.name,
            "description": store.description,
        },
        "theme": {
            "theme_template": store_theme_config.theme_template.name,
            "primary_color": store_theme_config.primary_color,
            "secondary_color": store_theme_config.secondary_color,
            "font_family": store_theme_config.font_family,
            "logo_url": store_theme_config.logo_url,
            "banner_url": store_theme_config.banner_url,
        },
    }


def apply_current_ai_draft_categories(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Apply only the categories section of the current temporary AI draft.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = _get_or_rebuild_draft_metadata(
        store=store,
        draft_payload=current_draft,
        draft_meta=get_ai_draft_meta(store.id),
        rebuild_partial=True,
    )
    if draft_meta.get("status") not in READY_FOR_REVIEW_WORKFLOW_STATUSES:
        raise ValidationError("Current workflow state is not ready_for_review")

    try:
        current_draft = validate_basic_draft_schema(current_draft)
        mode = detect_ai_response_mode(current_draft)
        if mode != "draft_ready":
            raise AIDraftSchemaValidationError("Current draft payload is not draft_ready")

        validated_categories = validate_categories_section(current_draft["categories"])
        category_names = [item["name"] for item in validated_categories]
        validate_products_section(current_draft["products"], category_names)
    except AIDraftSchemaValidationError as exc:
        raise ValidationError(str(exc)) from exc

    existing_categories_qs = get_store_categories_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=normalized_tenant_id,
    )
    existing_names_normalized = {
        _normalize_category_name_for_compare(category.name)
        for category in existing_categories_qs
    }

    created_categories: list[str] = []
    skipped_categories: list[str] = []

    try:
        with transaction.atomic():
            for item in validated_categories:
                draft_name = str(item["name"])
                normalized_name = _normalize_category_name_for_compare(draft_name)

                if normalized_name in existing_names_normalized:
                    skipped_categories.append(_normalize_category_name_for_store(draft_name))
                    continue

                safe_name = _normalize_category_name_for_store(draft_name)
                Category.objects.create(
                    store=store,
                    tenant_id=normalized_tenant_id,
                    name=safe_name,
                )
                existing_names_normalized.add(normalized_name)
                created_categories.append(safe_name)
    except Exception as exc:
        _log_and_audit_apply_failure(
            action="apply_categories",
            error_code=CATEGORY_APPLY_FAILED_ERROR_CODE,
            store=store,
            user=user,
            tenant_id=normalized_tenant_id,
            exc=exc,
        )
        raise ValidationError(CATEGORY_APPLY_FAILED_USER_MESSAGE) from exc

    return {
        "store_id": store.id,
        "draft_status": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "created_categories": created_categories,
        "skipped_categories": skipped_categories,
    }


def apply_current_ai_draft_products(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Apply only the products section of the current temporary AI draft.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = _get_or_rebuild_draft_metadata(
        store=store,
        draft_payload=current_draft,
        draft_meta=get_ai_draft_meta(store.id),
        rebuild_partial=True,
    )
    if draft_meta.get("status") not in READY_FOR_REVIEW_WORKFLOW_STATUSES:
        raise ValidationError("Current workflow state is not ready_for_review")

    try:
        current_draft = validate_basic_draft_schema(current_draft)
        mode = detect_ai_response_mode(current_draft)
        if mode != "draft_ready":
            raise AIDraftSchemaValidationError("Current draft payload is not draft_ready")

        validated_categories = validate_categories_section(current_draft["categories"])
        category_names = [item["name"] for item in validated_categories]
        validated_products = validate_products_section(current_draft["products"], category_names)
    except AIDraftSchemaValidationError as exc:
        raise ValidationError(str(exc)) from exc

    existing_categories_qs = get_store_categories_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=normalized_tenant_id,
    )
    category_by_normalized_name = {
        _normalize_category_name_for_compare(category.name): category
        for category in existing_categories_qs
    }

    for item in validated_products:
        normalized_category_name = _normalize_category_name_for_compare(
            str(item["category_name"])
        )
        if normalized_category_name not in category_by_normalized_name:
            raise ValidationError(
                "Failed to resolve product category_name to an existing category in this store"
            )

    existing_products_qs = get_store_products_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=normalized_tenant_id,
    )
    existing_skus_normalized = {
        _normalize_sku_for_compare(product.sku)
        for product in existing_products_qs
    }

    created_products: list[str] = []
    skipped_products: list[str] = []

    try:
        with transaction.atomic():
            for item in validated_products:
                draft_sku = str(item["sku"])
                normalized_sku = _normalize_sku_for_compare(draft_sku)

                if normalized_sku in existing_skus_normalized:
                    skipped_products.append(" ".join(draft_sku.strip().split()))
                    continue

                normalized_category_name = _normalize_category_name_for_compare(
                    str(item["category_name"])
                )
                resolved_category = category_by_normalized_name[normalized_category_name]

                safe_sku = " ".join(draft_sku.strip().split())
                created_product = Product.objects.create(
                    store=store,
                    tenant_id=normalized_tenant_id,
                    category=resolved_category,
                    name=str(item["name"]).strip(),
                    description=str(item["description"]),
                    price=item["price"],
                    sku=safe_sku,
                )

                Inventory.objects.create(
                    product=created_product,
                    stock_quantity=item["stock_quantity"],
                )

                image_url = str(item["image_url"]).strip()
                if image_url:
                    ProductImage.objects.create(
                        product=created_product,
                        image_url=image_url,
                    )
                existing_skus_normalized.add(normalized_sku)
                created_products.append(safe_sku)
    except Exception as exc:
        _log_and_audit_apply_failure(
            action="apply_products",
            error_code=PRODUCT_APPLY_FAILED_ERROR_CODE,
            store=store,
            user=user,
            tenant_id=normalized_tenant_id,
            exc=exc,
        )
        raise ValidationError(PRODUCT_APPLY_FAILED_USER_MESSAGE) from exc

    return {
        "store_id": store.id,
        "draft_status": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "created_products": created_products,
        "skipped_products": skipped_products,
    }


def apply_current_ai_draft_to_store(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Confirm/apply the current AI draft completely using existing sub-services.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    _write_ai_audit_log(
        tenant_id=normalized_tenant_id,
        store_id=store.id,
        actor_id=getattr(user, "id", None),
        action="apply_draft",
        status="requested",
        message="Apply current AI draft requested.",
    )

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="apply_draft",
            status="failed",
            message="No temporary AI draft found for this store.",
        )
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = _get_or_rebuild_draft_metadata(
        store=store,
        draft_payload=current_draft,
        draft_meta=get_ai_draft_meta(store.id),
        rebuild_partial=True,
    )
    if draft_meta.get("status") not in READY_FOR_REVIEW_WORKFLOW_STATUSES:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="apply_draft",
            status="failed",
            message="Current workflow state is not ready_for_review.",
        )
        raise ValidationError("Current workflow state is not ready_for_review")

    def _cleanup_draft_after_commit() -> None:
        try:
            delete_ai_draft(store.id)
            delete_ai_draft_meta(store.id)
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Draft cleanup after apply commit failed. store_id=%s, reason=%s",
                store.id,
                str(exc),
            )

    try:
        with transaction.atomic():
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )
            categories_result = apply_current_ai_draft_categories(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )
            products_result = apply_current_ai_draft_products(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )

            store.status = "setup"
            store.save(update_fields=["status", "updated_at"])

            transaction.on_commit(_cleanup_draft_after_commit)
    except Exception as exc:
        technical_reason = _technical_exception_reason(exc)
        logger.warning(
            "Full AI draft apply failed. store_id=%s, tenant_id=%s, reason=%s",
            store.id,
            normalized_tenant_id,
            technical_reason,
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="apply_draft",
            status="failed",
            message=technical_reason,
        )
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(STORE_CORE_APPLY_FAILED_USER_MESSAGE) from exc

    _write_ai_audit_log(
        tenant_id=normalized_tenant_id,
        store_id=store.id,
        actor_id=getattr(user, "id", None),
        action="apply_draft",
        status="completed",
        message="Current AI draft applied successfully.",
    )
    return {
        "store_id": store.id,
        "workflow_status": WORKFLOW_STATUS_APPLIED,
        "store_status": "setup",
        "store_core_applied": True,
        "categories": {
            "created": categories_result.get("created_categories", []),
            "skipped": categories_result.get("skipped_categories", []),
        },
        "products": {
            "created": products_result.get("created_products", []),
            "skipped": products_result.get("skipped_products", []),
        },
        "draft_cleanup_scheduled": True,
    }


__all__ = [
    "apply_current_ai_draft_categories",
    "apply_current_ai_draft_products",
    "apply_current_ai_draft_store_core",
    "apply_current_ai_draft_to_store",
]
