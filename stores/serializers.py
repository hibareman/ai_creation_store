from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from .models import Store, StoreSettings, StoreDomain

class StoreSerializer(serializers.ModelSerializer):
    """
    Serializer for Store model.
    
    **Features:**
    - Multi-tenant isolation (tenant_id)
    - Unique slug per tenant
    - Status tracking (active, inactive, archived)
    - Timestamps (created_at, updated_at)
    
    **Read-Only Fields:**
    - id: Auto-generated store ID
    - owner: Set from authenticated user
    - tenant_id: Set from JWT token
    - created_at, updated_at: Auto-managed
    """
    
    class Meta:
        model = Store
        fields = ['id', 'owner', 'name', 'slug', 'description', 'status', 'tenant_id', 'created_at', 'updated_at']
        read_only_fields = ['id', 'tenant_id', 'created_at', 'updated_at', 'owner']
        extra_kwargs = {
            'slug': {'validators': []},
            'name': {
                'help_text': 'Store display name (max 255 characters)',
                'max_length': 255,
            },
            'slug': {
                'help_text': 'URL-friendly identifier (lowercase, dashes allowed)',
                'max_length': 255,
            },
            'description': {
                'help_text': 'Store description/biography',
                'required': False,
            },
            'status': {
                'help_text': 'Store status: active, inactive, or archived',
                'default': 'active',
            },
        }


class StoreSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer for StoreSettings model.
    
    **Purpose:** Configure store-specific settings (currency, language, timezone)
    
    **Read-Only Fields:**
    - id: Settings ID
    - store: Automatically set to authenticated store
    - created_at, updated_at: Auto-managed
    
    **Writable Fields:**
    - currency: ISO 4217 code (e.g., EUR, USD)
    - language: Language code (e.g., en, ar)
    - timezone: IANA timezone (e.g., Europe/Berlin)
    """
    
    class Meta:
        model = StoreSettings
        fields = ['id', 'store', 'currency', 'language', 'timezone', 'created_at', 'updated_at']
        read_only_fields = ['id', 'store', 'created_at', 'updated_at']
        extra_kwargs = {
            'currency': {
                'help_text': 'ISO 4217 currency code',
                'max_length': 3,
            },
            'language': {
                'help_text': 'Language code (e.g., en, ar, de)',
                'max_length': 10,
            },
            'timezone': {
                'help_text': 'IANA timezone identifier',
                'max_length': 50,
            },
        }


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