import logging
import mimetypes
from pathlib import Path
import uuid

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
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


def update_store_appearance(
    user,
    store,
    *,
    primary_color=None,
    background_color=None,
    font=None,
    style=None,
    logo_url=None,
):
    """
    Update or create store appearance using the existing StoreThemeConfig model.
    """
    _validate_store_authorization(user, store)

    config = selectors.get_store_theme_config(store)
    resolved_template = None

    if style is not None:
        resolved_template = selectors.get_theme_template_by_name(style)
        if not resolved_template:
            raise ValidationError("Invalid style. No matching theme template was found.")

    if config is None:
        missing_fields = []
        if resolved_template is None:
            missing_fields.append("style")
        if primary_color is None:
            missing_fields.append("primaryColor")
        if background_color is None:
            missing_fields.append("backgroundColor")
        if font is None:
            missing_fields.append("font")

        if missing_fields:
            raise ValidationError(
                "Store appearance does not exist yet. Missing required fields for initial creation: "
                + ", ".join(missing_fields)
            )

        with transaction.atomic():
            config = StoreThemeConfig.objects.create(
                store=store,
                theme_template=resolved_template,
                primary_color=primary_color,
                secondary_color=background_color,
                font_family=font,
                logo_url=logo_url or "",
                banner_url="",
            )

        logger.info(
            "Store appearance created: store_id=%s, theme_config_id=%s, tenant_id=%s",
            store.id,
            config.id,
            store.tenant_id,
        )
        return config

    if config.store_id != store.id:
        logger.warning(
            "Cross-store violation on appearance update: store_id=%s, theme_config_id=%s, config_store_id=%s",
            store.id,
            config.id,
            config.store_id,
        )
        raise PermissionDenied("You cannot modify this appearance configuration")

    if resolved_template is not None:
        config.theme_template = resolved_template

    if primary_color is not None:
        config.primary_color = primary_color

    if background_color is not None:
        config.secondary_color = background_color

    if font is not None:
        config.font_family = font

    if logo_url is not None:
        config.logo_url = logo_url or ""

    with transaction.atomic():
        config.save()

    logger.info(
        "Store appearance updated: store_id=%s, theme_config_id=%s, tenant_id=%s",
        store.id,
        config.id,
        store.tenant_id,
    )

    return config


def _resolve_image_extension(file_name: str, mime_type: str) -> str:
    raw_suffix = Path(file_name or "").suffix.lower()
    if raw_suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
        return raw_suffix

    mime_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
    }
    return mime_map.get((mime_type or "").lower(), ".png")


def upload_store_logo_asset(
    user,
    store,
    *,
    file_obj,
    alt: str = "",
    absolute_url_builder=None,
):
    """
    Upload store logo file and update StoreThemeConfig.logo_url.
    """
    _validate_store_authorization(user, store)

    if not file_obj:
        raise ValidationError("Logo file is required.")

    mime_type = (
        getattr(file_obj, "content_type", "")
        or mimetypes.guess_type(getattr(file_obj, "name", "") or "")[0]
        or ""
    )
    if not mime_type.startswith("image/"):
        raise ValidationError("Uploaded file must be an image.")

    config = selectors.get_store_theme_config(store)
    if config is None:
        raise ValidationError("Store appearance configuration does not exist.")

    file_token = uuid.uuid4().hex
    ext = _resolve_image_extension(getattr(file_obj, "name", ""), mime_type)
    store_key = (store.slug or str(store.id)).strip().lower()
    file_path = f"stores/{store_key}/assets/logo/{file_token}{ext}"
    saved_path = default_storage.save(file_path, file_obj)
    storage_url = default_storage.url(saved_path)

    final_url = (
        absolute_url_builder(storage_url)
        if callable(absolute_url_builder)
        else storage_url
    )
    if not isinstance(final_url, str) or not final_url.startswith(("http://", "https://")):
        raise ValidationError("Failed to generate a valid logo URL.")

    with transaction.atomic():
        config.logo_url = final_url
        config.save(update_fields=["logo_url", "updated_at"])

    resolved_alt = (alt or "").strip() or f"{store.name} logo"
    asset_id = f"logo_{store.id}_{file_token[:6]}"

    return {
        "asset_id": asset_id,
        "url": final_url,
        "alt": resolved_alt,
        "mime_type": mime_type,
    }
