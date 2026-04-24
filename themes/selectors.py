from .models import StoreThemeConfig, ThemeTemplate


def get_active_theme_templates():
    """
    Return ready-to-use theme templates.

    The approved contract does not include an explicit active flag yet,
    so all stored templates are treated as active in this foundation phase.
    """
    return ThemeTemplate.objects.all().order_by("name")


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

    return ThemeTemplate.objects.filter(id=theme_template_id).first()


def get_theme_template_by_name(theme_template_name):
    """
    Return a single theme template by name (case-insensitive), if it exists.
    """
    if not isinstance(theme_template_name, str) or not theme_template_name.strip():
        return None

    return ThemeTemplate.objects.filter(name__iexact=theme_template_name.strip()).first()
