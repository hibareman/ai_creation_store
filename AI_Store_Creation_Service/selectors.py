"""
Read-only selectors for AI Store Creation workflow.
"""

from __future__ import annotations

from categories.models import Category
from products.models import Product
from stores.models import Store
from themes.models import StoreThemeConfig, ThemeTemplate


def get_store_for_ai_flow(store_id: int, user, tenant_id: int | None):
    """
    Return store only if it belongs to the authenticated user and trusted tenant context.

    Multi-tenant access rules enforced at query level:
    - store exists
    - store.tenant_id == request.tenant_id (trusted middleware context)
    - store.owner_id == user.id
    """
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    user_id = getattr(user, "id", None)

    if not is_authenticated or user_id is None or tenant_id is None:
        return None

    return (
        Store.objects.filter(
            id=store_id,
            tenant_id=tenant_id,
            owner_id=user_id,
        )
        .select_related("owner")
        .first()
    )


def get_store_theme_config_for_ai_flow(store_id: int, user, tenant_id: int | None):
    """
    Return StoreThemeConfig only if store access is valid for user + trusted tenant context.

    Multi-tenant access rules enforced at query level:
    - target store exists
    - store.tenant_id == request.tenant_id (trusted middleware context)
    - store.owner_id == request.user.id
    """
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    user_id = getattr(user, "id", None)

    if not is_authenticated or user_id is None or tenant_id is None:
        return None

    return (
        StoreThemeConfig.objects.filter(
            store_id=store_id,
            store__tenant_id=tenant_id,
            store__owner_id=user_id,
        )
        .select_related("store", "theme_template")
        .first()
    )


def get_store_categories_for_ai_flow(store_id: int, user, tenant_id: int | None):
    """
    Return categories only when store access is valid for user + trusted tenant context.

    Multi-tenant access rules enforced at query level:
    - user is authenticated
    - store.tenant_id == request.tenant_id (trusted middleware context)
    - store.owner_id == request.user.id
    """
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    user_id = getattr(user, "id", None)

    if not is_authenticated or user_id is None or tenant_id is None:
        return Category.objects.none()

    return (
        Category.objects.filter(
            store_id=store_id,
            tenant_id=tenant_id,
            store__tenant_id=tenant_id,
            store__owner_id=user_id,
        )
        .select_related("store")
        .order_by("created_at")
    )


def get_store_products_for_ai_flow(store_id: int, user, tenant_id: int | None):
    """
    Return products only when store access is valid for user + trusted tenant context.

    Multi-tenant access rules enforced at query level:
    - user is authenticated
    - store.tenant_id == request.tenant_id (trusted middleware context)
    - store.owner_id == request.user.id
    """
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    user_id = getattr(user, "id", None)

    if not is_authenticated or user_id is None or tenant_id is None:
        return Product.objects.none()

    return (
        Product.objects.filter(
            store_id=store_id,
            tenant_id=tenant_id,
            store__tenant_id=tenant_id,
            store__owner_id=user_id,
        )
        .select_related("store", "category")
        .order_by("-created_at")
    )


def get_available_theme_template_names() -> list[str]:
    """
    Return currently available ThemeTemplate names as a predictable list[str].
    """
    return list(
        ThemeTemplate.objects.order_by("name").values_list("name", flat=True)
    )
