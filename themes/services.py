import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from .models import StoreThemeConfig
from . import selectors

logger = logging.getLogger(__name__)


def _validate_store_authorization(user, store):
    """
    Validate trusted store-scoped access before any theme write operation.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Authentication required")

    if not store:
        raise ValidationError("Store is required")

    if user.tenant_id != store.tenant_id:
        logger.warning(
            "Multi-tenant violation: user_id=%s, user_tenant_id=%s, store_id=%s, store_tenant_id=%s",
            user.id,
            user.tenant_id,
            store.id,
            store.tenant_id,
        )
        raise PermissionDenied("You do not have access to this store")

    if user.id != store.owner_id:
        logger.warning(
            "Ownership violation: user_id=%s, store_id=%s, store_owner_id=%s",
            user.id,
            store.id,
            store.owner_id,
        )
        raise PermissionDenied("You do not own this store")


def _get_valid_theme_template(theme_template_id):
    """
    Resolve and validate a theme template from a trusted service input.
    """
    theme_template = selectors.get_theme_template_by_id(theme_template_id)
    if not theme_template:
        raise ValidationError("Selected theme template does not exist")
    return theme_template


def get_or_create_store_theme_config(
    user,
    store,
    theme_template_id,
    primary_color,
    secondary_color,
    font_family,
    logo_url="",
    banner_url="",
):
    """
    Return the store theme config if it exists, otherwise create it.
    """
    _validate_store_authorization(user, store)

    existing_config = selectors.get_store_theme_config(store)
    if existing_config:
        return existing_config

    theme_template = _get_valid_theme_template(theme_template_id)

    with transaction.atomic():
        config = StoreThemeConfig.objects.create(
            store=store,
            theme_template=theme_template,
            primary_color=primary_color,
            secondary_color=secondary_color,
            font_family=font_family,
            logo_url=logo_url or "",
            banner_url=banner_url or "",
        )

    logger.info(
        "Store theme config created: store_id=%s, theme_config_id=%s, theme_template_id=%s, tenant_id=%s",
        store.id,
        config.id,
        theme_template.id,
        store.tenant_id,
    )

    return config


def update_store_theme_config(
    user,
    store,
    theme_template_id=None,
    primary_color=None,
    secondary_color=None,
    font_family=None,
    logo_url=None,
    banner_url=None,
):
    """
    Update an existing store theme configuration within the store boundary.
    """
    _validate_store_authorization(user, store)

    config = selectors.get_store_theme_config(store)
    if not config:
        raise ValidationError("Store theme configuration does not exist")

    if config.store_id != store.id:
        logger.warning(
            "Cross-store violation: store_id=%s, theme_config_id=%s, config_store_id=%s",
            store.id,
            config.id,
            config.store_id,
        )
        raise PermissionDenied("You cannot modify this theme configuration")

    if theme_template_id is not None:
        config.theme_template = _get_valid_theme_template(theme_template_id)

    if primary_color is not None:
        config.primary_color = primary_color

    if secondary_color is not None:
        config.secondary_color = secondary_color

    if font_family is not None:
        config.font_family = font_family

    if logo_url is not None:
        config.logo_url = logo_url or ""

    if banner_url is not None:
        config.banner_url = banner_url or ""

    with transaction.atomic():
        config.save()

    logger.info(
        "Store theme config updated: store_id=%s, theme_config_id=%s, tenant_id=%s",
        store.id,
        config.id,
        store.tenant_id,
    )

    return config
