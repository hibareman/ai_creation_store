from rest_framework import serializers
from .models import Store, StoreSettings, StoreDomain

class StoreSerializer(serializers.ModelSerializer):
    """
    Serializer for Store model.
    
    **Features:**
    - Multi-tenant isolation (tenant_id)
    - Unique slug per tenant
    - Status tracking (setup, active, inactive)
    - Timestamps (created_at, updated_at)
    
    **Read-Only Fields:**
    - id: Auto-generated store ID
    - owner: Set from authenticated user
    - tenant_id: Set from JWT token
    - created_at, updated_at: Auto-managed
    """
    
    class Meta:
        model = Store
        fields = [
            'id',
            'owner',
            'name',
            'slug',
            'subdomain',
            'description',
            'status',
            'tenant_id',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'tenant_id', 'created_at', 'updated_at', 'owner', 'subdomain']
        extra_kwargs = {
            'name': {
                'help_text': 'Store display name (max 255 characters)',
                'max_length': 255,
            },
            'slug': {
                'validators': [],
                'help_text': 'URL-friendly identifier (lowercase, dashes allowed)',
                'max_length': 255,
            },
            'description': {
                'help_text': 'Store description/biography',
                'required': False,
            },
            'status': {
                'help_text': 'Store status: setup, active, or inactive',
                'default': 'setup',
            },
        }


class StoreSettingsDataSerializer(serializers.Serializer):
    storeName = serializers.CharField(source='store.name', read_only=True)
    storeUrl = serializers.CharField(source='store.slug', read_only=True)
    storeSubdomain = serializers.CharField(source='store.subdomain', read_only=True, allow_null=True)
    storeDescription = serializers.CharField(source='store.description', read_only=True)
    storeEmail = serializers.EmailField(source='store_email', read_only=True, allow_blank=True)
    storePhone = serializers.CharField(source='store_phone', read_only=True, allow_blank=True)
    currency = serializers.CharField(read_only=True)
    timezone = serializers.CharField(read_only=True)
    language = serializers.CharField(read_only=True)
    emailNotifications = serializers.BooleanField(source='email_notifications', read_only=True)
    orderNotifications = serializers.BooleanField(source='order_notifications', read_only=True)
    marketingNotifications = serializers.BooleanField(source='marketing_notifications', read_only=True)
    twoFactorAuth = serializers.BooleanField(source='two_factor_auth', read_only=True)


class StoreSettingsSerializer(serializers.Serializer):
    store_id = serializers.SerializerMethodField()
    settings = StoreSettingsDataSerializer(source='*', read_only=True)

    def get_store_id(self, obj):
        store = getattr(obj, 'store', None)
        if not store:
            return None
        return str(store.slug or store.id)


class StoreSettingsUpdateSerializer(serializers.Serializer):
    storeName = serializers.CharField(required=False, allow_blank=False, max_length=255)
    storeUrl = serializers.CharField(required=False, allow_blank=False, max_length=255)
    storeDescription = serializers.CharField(required=False, allow_blank=True)
    storeEmail = serializers.EmailField(required=False, allow_blank=True)
    storePhone = serializers.CharField(required=False, allow_blank=True, max_length=30)
    currency = serializers.CharField(required=False, allow_blank=False, max_length=3)
    timezone = serializers.CharField(required=False, allow_blank=False, max_length=50)
    language = serializers.CharField(required=False, allow_blank=False, max_length=10)
    emailNotifications = serializers.BooleanField(required=False)
    orderNotifications = serializers.BooleanField(required=False)
    marketingNotifications = serializers.BooleanField(required=False)
    twoFactorAuth = serializers.BooleanField(required=False)

    def validate_storeName(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("storeName cannot be empty.")
        return cleaned

    def validate_storeUrl(self, value):
        cleaned = value.strip().lower()
        if not cleaned:
            raise serializers.ValidationError("storeUrl cannot be empty.")
        return cleaned

    def validate_storeDescription(self, value):
        return value.strip() if isinstance(value, str) else value

    def validate_storePhone(self, value):
        return value.strip() if isinstance(value, str) else value

    def validate_currency(self, value):
        return value.strip().upper()

    def validate_timezone(self, value):
        return value.strip()

    def validate_language(self, value):
        return value.strip().lower()


class StoreSettingsUpdateRequestSerializer(serializers.Serializer):
    settings = StoreSettingsUpdateSerializer()


class StoreDomainSerializer(serializers.ModelSerializer):
    """
    Serializer for StoreDomain model.
    
    **Purpose:** Manage custom domains for stores
    
    **Read-Only Fields:**
    - id: Domain record ID
    - store: Automatically set to authenticated store
    - created_at, updated_at: Auto-managed
    
    **Writable Fields:**
    - domain: Full domain name (e.g., mystore.com)
    - is_primary: Mark as primary domain for store
    """
    
    class Meta:
        model = StoreDomain
        fields = ['id', 'store', 'domain', 'is_primary', 'created_at', 'updated_at']
        read_only_fields = ['id', 'store', 'created_at', 'updated_at']
        extra_kwargs = {
            'domain': {
                'help_text': 'Full domain name (e.g., mystore.com)',
                'max_length': 255,
            },
            'is_primary': {
                'help_text': 'Mark as primary domain for store',
                'default': False,
            },
        }


class CheckSlugSerializer(serializers.Serializer):
    """
    Serializer for checking slug availability.
    
    **Purpose:** Validate if a slug is available for a store
    
    **Fields:**
    - slug (required): The slug to check
    - store_id (optional): Store ID to validate within tenant
    """
    slug = serializers.SlugField(
        max_length=255,
        required=True,
        help_text='Slug to check for availability'
    )
    store_id = serializers.IntegerField(
        required=False,
        help_text='Store ID for uniqueness validation'
    )


class SuggestSlugSerializer(serializers.Serializer):
    """
    Serializer for suggesting slugs based on store name.
    
    **Purpose:** Generate multiple slug suggestions from store name
    
    **Fields:**
    - name (required): Store name to generate slugs from
    - store_id (optional): Store ID for validation
    - limit (optional): Number of suggestions (1-10, default 5)
    
    **Response:** Returns list of suggested slug options
    """
    name = serializers.CharField(
        max_length=255,
        required=True,
        help_text='Store name to generate slugs from'
    )
    store_id = serializers.IntegerField(
        required=False,
        help_text='Store ID for uniqueness validation'
    )
    limit = serializers.IntegerField(
        default=5,
        min_value=1,
        max_value=10,
        help_text='Number of slug suggestions to return (1-10)'
    )


class PublishStoreRequestSerializer(serializers.Serializer):
    """Request serializer for publish/unpublish actions."""
    action = serializers.ChoiceField(choices=["publish", "unpublish"])


class StorePublishStateSerializer(serializers.Serializer):
    """Serializer for store publish state."""
    is_published = serializers.BooleanField()
    published_at = serializers.DateTimeField(allow_null=True)


class StorePublishResponseSerializer(serializers.Serializer):
    """Response serializer for publish/unpublish operations."""
    message = serializers.CharField()
    store = StorePublishStateSerializer()


class SetStoreSubdomainRequestSerializer(serializers.Serializer):
    """Request serializer for setting store subdomain."""
    subdomain = serializers.CharField(max_length=255, required=True)

    def validate_subdomain(self, value):
        normalized = value.strip().lower()
        if not normalized:
            raise serializers.ValidationError("Subdomain cannot be empty")
        return normalized


class StoreSubdomainStateSerializer(serializers.Serializer):
    """Serializer for store subdomain state."""
    subdomain = serializers.CharField(allow_null=True)


class StoreSubdomainResponseSerializer(serializers.Serializer):
    """Response serializer for set-subdomain operation."""
    message = serializers.CharField()
    store = StoreSubdomainStateSerializer()


class PublicStoreSerializer(serializers.ModelSerializer):
    """Public-safe representation of a store."""

    class Meta:
        model = Store
        fields = ['id', 'name', 'subdomain', 'description']
