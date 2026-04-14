from rest_framework import serializers

from .models import StoreThemeConfig, ThemeTemplate


class ThemeTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for representing available theme templates.
    """

    class Meta:
        model = ThemeTemplate
        fields = ["id", "name", "description", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "name": {
                "help_text": "Theme template name",
                "max_length": 255,
            },
            "description": {
                "help_text": "Theme template description",
                "required": False,
            },
        }


class StoreThemeConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for reading the current store theme configuration.
    """

    theme_template = ThemeTemplateSerializer(read_only=True)
    store = serializers.IntegerField(source="store_id", read_only=True)

    class Meta:
        model = StoreThemeConfig
        fields = [
            "id",
            "store",
            "theme_template",
            "primary_color",
            "secondary_color",
            "font_family",
            "logo_url",
            "banner_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "store",
            "theme_template",
            "created_at",
            "updated_at",
        ]


class StoreThemeConfigUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating editable store theme configuration fields only.
    """

    class Meta:
        model = StoreThemeConfig
        fields = [
            "theme_template",
            "primary_color",
            "secondary_color",
            "font_family",
            "logo_url",
            "banner_url",
        ]
        extra_kwargs = {
            "theme_template": {
                "help_text": "Selected theme template ID",
                "required": False,
            },
            "primary_color": {
                "help_text": "Primary brand color",
                "required": False,
                "max_length": 20,
            },
            "secondary_color": {
                "help_text": "Secondary brand color",
                "required": False,
                "max_length": 20,
            },
            "font_family": {
                "help_text": "Preferred font family",
                "required": False,
                "max_length": 100,
            },
            "logo_url": {
                "help_text": "Store logo URL",
                "required": False,
                "allow_blank": True,
            },
            "banner_url": {
                "help_text": "Store banner URL",
                "required": False,
                "allow_blank": True,
            },
        }

    def validate_primary_color(self, value):
        return value.strip() if value else value

    def validate_secondary_color(self, value):
        return value.strip() if value else value

    def validate_font_family(self, value):
        if value and not value.strip():
            raise serializers.ValidationError("Font family cannot be empty")
        return value.strip() if value else value

    def validate_logo_url(self, value):
        return value.strip() if value else ""

    def validate_banner_url(self, value):
        return value.strip() if value else ""
