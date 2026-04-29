from collections.abc import Mapping
from decimal import Decimal
import re

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from platform_admin.models import PlatformAdminSettings
from stores.models import Store
from users.models import User

BACKEND_TO_ADMIN_STATUS = {
    "active": "active",
    "setup": "pending",
    "draft": "pending",
    "inactive": "suspended",
}

ADMIN_TO_BACKEND_STATUS = {
    "active": "active",
    "pending": "setup",
    "suspended": "inactive",
}

ADMIN_STATUS_CHOICES = tuple(ADMIN_TO_BACKEND_STATUS.keys())


def map_backend_status_to_admin(status):
    return BACKEND_TO_ADMIN_STATUS.get(status, "pending")


def map_admin_status_to_backend(status):
    return ADMIN_TO_BACKEND_STATUS[status]


def decimal_to_json_number(value):
    if value is None:
        return 0
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def map_backend_role_to_admin(role):
    role = role or ""
    if role == "Super Admin":
        return "super_admin"
    if role == "Store Owner":
        return "store_owner"
    if role in {"Support", "support"}:
        return "support"
    return re.sub(r"[^a-z0-9]+", "_", role.strip().lower()).strip("_")


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data) - set(self.fields)
            if unknown_fields:
                raise serializers.ValidationError(
                    {field: ["Unknown field."] for field in sorted(unknown_fields)}
                )
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if not isinstance(data, bool):
            self.fail("invalid", input=data)
        return super().to_internal_value(data)


class StoreAdminSummarySerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    status = serializers.SerializerMethodField()
    products_count = serializers.IntegerField(read_only=True)
    orders_count = serializers.IntegerField(read_only=True)
    revenue_total = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "owner_name",
            "owner_email",
            "status",
            "products_count",
            "orders_count",
            "revenue_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_owner_name(self, obj):
        owner = obj.owner
        full_name = f"{owner.first_name} {owner.last_name}".strip()
        return full_name or owner.username or ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_status(self, obj):
        return map_backend_status_to_admin(obj.status)

    @extend_schema_field(OpenApiTypes.NUMBER)
    def get_revenue_total(self, obj):
        return decimal_to_json_number(getattr(obj, "revenue_total", None))


class AdminStoresListResponseSerializer(serializers.Serializer):
    items = StoreAdminSummarySerializer(many=True)


class AdminStatsSerializer(serializers.Serializer):
    total_stores = serializers.IntegerField()
    active_users = serializers.IntegerField()
    total_orders = serializers.IntegerField()
    platform_revenue = serializers.FloatField()


class AdminStoreStatusBreakdownSerializer(serializers.Serializer):
    active = serializers.IntegerField()
    pending = serializers.IntegerField()
    suspended = serializers.IntegerField()


class AdminDashboardResponseSerializer(serializers.Serializer):
    stats = AdminStatsSerializer()
    store_status = AdminStoreStatusBreakdownSerializer()
    recent_stores = StoreAdminSummarySerializer(many=True)


class StoreStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ADMIN_STATUS_CHOICES)


class StoreStatusUpdateResponseSerializer(serializers.Serializer):
    store = StoreAdminSummarySerializer()


class AdminUserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    stores_count = serializers.IntegerField(read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "role",
            "stores_count",
            "status",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_full_name(self, obj):
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return full_name or obj.username or obj.email

    @extend_schema_field(OpenApiTypes.STR)
    def get_role(self, obj):
        return map_backend_role_to_admin(obj.role)

    @extend_schema_field(OpenApiTypes.STR)
    def get_status(self, obj):
        return "active" if obj.is_active else "suspended"


class AdminUsersListResponseSerializer(serializers.Serializer):
    items = AdminUserSummarySerializer(many=True)


class AdminPlatformSettingsDataSerializer(StrictSerializer):
    support_email = serializers.EmailField()
    default_currency = serializers.CharField(max_length=3)
    allow_public_registration = StrictBooleanField()
    require_store_approval = StrictBooleanField()
    maintenance_mode = StrictBooleanField()

    def validate_default_currency(self, value):
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise serializers.ValidationError(
                "Default currency must be an uppercase 3-letter currency code."
            )
        return value

    def to_representation(self, instance):
        if isinstance(instance, PlatformAdminSettings):
            return {
                "support_email": instance.support_email,
                "default_currency": instance.default_currency,
                "allow_public_registration": instance.allow_public_registration,
                "require_store_approval": instance.require_store_approval,
                "maintenance_mode": instance.maintenance_mode,
            }
        return super().to_representation(instance)


class AdminPlatformSettingsResponseSerializer(serializers.Serializer):
    settings = AdminPlatformSettingsDataSerializer()


class AdminPlatformSettingsUpdateRequestSerializer(StrictSerializer):
    settings = AdminPlatformSettingsDataSerializer()

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data) - {"settings"}
            if unknown_fields:
                raise serializers.ValidationError(
                    {field: ["Unknown field."] for field in sorted(unknown_fields)}
                )
        if not isinstance(data, Mapping) or "settings" not in data:
            raise serializers.ValidationError(
                {"settings": ["This field is required."]}
            )

        settings_payload = data["settings"]
        if not isinstance(settings_payload, Mapping):
            raise serializers.ValidationError(
                {"settings": ["Expected an object."]}
            )

        settings_serializer = AdminPlatformSettingsDataSerializer(
            data=settings_payload,
            partial=True,
        )
        settings_serializer.is_valid(raise_exception=True)
        return {"settings": settings_serializer.validated_data}
