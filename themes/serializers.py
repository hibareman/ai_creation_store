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


class AppearanceDataSerializer(serializers.Serializer):
    primaryColor = serializers.CharField(source="primary_color", read_only=True)
    backgroundColor = serializers.CharField(source="secondary_color", read_only=True)
    font = serializers.CharField(source="font_family", read_only=True)
    style = serializers.SerializerMethodField()
    logoUrl = serializers.CharField(source="logo_url", read_only=True)

    def get_style(self, obj):
        template = getattr(obj, "theme_template", None)
        if not template or not getattr(template, "name", None):
            return ""
        return str(template.name).strip().lower()


class StoreAppearanceSerializer(serializers.Serializer):
    store_id = serializers.SerializerMethodField()
    appearance = AppearanceDataSerializer(source="*", read_only=True)

    def get_store_id(self, obj):
        store = getattr(obj, "store", None)
        if not store:
            return None
        return str(store.slug or store.id)


class AppearanceUpdateSerializer(serializers.Serializer):
    primaryColor = serializers.CharField(required=False, max_length=20)
    backgroundColor = serializers.CharField(required=False, max_length=20)
    font = serializers.CharField(required=False, max_length=100)
    style = serializers.CharField(required=False, max_length=255)
    logoUrl = serializers.URLField(required=False, allow_blank=True)

    def validate_primaryColor(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("primaryColor cannot be empty.")
        return cleaned

    def validate_backgroundColor(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("backgroundColor cannot be empty.")
        return cleaned

    def validate_font(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("font cannot be empty.")
        return cleaned

    def validate_style(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("style cannot be empty.")
        return cleaned

    def validate_logoUrl(self, value):
        return value.strip() if isinstance(value, str) else value


class AppearanceUpdateRequestSerializer(serializers.Serializer):
    appearance = AppearanceUpdateSerializer()


class StoreLogoUploadRequestSerializer(serializers.Serializer):
    file = serializers.ImageField(required=True)
    alt = serializers.CharField(required=False, allow_blank=True, max_length=255)


class StoreLogoUploadResponseSerializer(serializers.Serializer):
    asset_id = serializers.CharField()
    url = serializers.URLField()
    alt = serializers.CharField()
    mime_type = serializers.CharField()
