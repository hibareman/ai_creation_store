from django.db import transaction
from django.db.models import Case, IntegerField, Value, When

from .models import StoreThemeConfig, ThemeTemplate


LEGACY_THEME_NAME_ALIASES = {
    "elegant": "classic",
    "natural": "minimal",
}

CORE_THEME_TEMPLATES = (
    {
        "name": "Modern",
        "description": "A clean contemporary storefront theme for general-purpose shops.",
    },
    {
        "name": "Minimal",
        "description": "A simple low-distraction theme focused on clarity and product visibility.",
    },
    {
        "name": "Classic",
        "description": "A familiar traditional storefront theme with a balanced presentation style.",
    },
    {
        "name": "Bold",
        "description": "A vibrant storefront theme for high-energy brands and campaigns.",
    },
)


def ensure_core_theme_templates():
    """
    Ensure the baseline theme templates required by the frontend exist.
    """
    with transaction.atomic():
        for template in CORE_THEME_TEMPLATES:
            existing_template = (
                ThemeTemplate.objects.filter(name__iexact=template["name"])
                .order_by("id")
                .first()
            )
            if existing_template:
                continue
            ThemeTemplate.objects.create(
                name=template["name"],
                description=template["description"],
            )


def get_active_theme_templates():
    """
    Return ready-to-use theme templates.

    The approved contract does not include an explicit active flag yet,
    so all stored templates are treated as active in this foundation phase.
    """
    ensure_core_theme_templates()

    ordered_names = [template["name"] for template in CORE_THEME_TEMPLATES]
    ordering = Case(
        *[
            When(name__iexact=name, then=Value(index))
            for index, name in enumerate(ordered_names)
        ],
        default=Value(len(ordered_names)),
        output_field=IntegerField(),
    )

    return ThemeTemplate.objects.all().order_by(ordering, "name")


def get_first_active_theme_template():
    """
    Return the first available theme template using the standard active ordering.
    """
    return get_active_theme_templates().first()


def get_store_theme_config(store):
    """
    Return the theme configuration for a store, if it exists.
    """
    if not store:
        return None

    return (
        StoreThemeConfig.objects.filter(store=store)
        .select_related("store", "theme_template")
        .first()
    )


def get_theme_template_by_id(theme_template_id):
    """
    Return a single theme template by ID, if it exists.
    """
    if not theme_template_id:
        return None

    ensure_core_theme_templates()
    return ThemeTemplate.objects.filter(id=theme_template_id).first()


def get_theme_template_by_name(theme_template_name):
    """
    Return a single theme template by name (case-insensitive), if it exists.
    """
    if not isinstance(theme_template_name, str) or not theme_template_name.strip():
        return None

    ensure_core_theme_templates()

    normalized_name = theme_template_name.strip().lower()
    resolved_name = LEGACY_THEME_NAME_ALIASES.get(normalized_name, normalized_name)
    return ThemeTemplate.objects.filter(name__iexact=resolved_name).order_by("id").first()
