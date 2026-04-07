from rest_framework import serializers
from .models import Store, StoreSettings, StoreDomain

class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ['id', 'owner', 'name', 'slug', 'description', 'status', 'tenant_id', 'created_at', 'updated_at']
        read_only_fields = ['id', 'slug', 'tenant_id', 'created_at', 'updated_at', 'owner']


class StoreSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer for StoreSettings model.
    store field is read_only as it's linked automatically to the Store.
    """
    class Meta:
        model = StoreSettings
        fields = ['id', 'store', 'currency', 'language', 'timezone', 'created_at', 'updated_at']
        read_only_fields = ['id', 'store', 'created_at', 'updated_at']


class StoreDomainSerializer(serializers.ModelSerializer):
    """
    Serializer for StoreDomain model.
    store field is read_only as it's linked automatically to the Store.
    """
    class Meta:
        model = StoreDomain
        fields = ['id', 'store', 'domain', 'is_primary', 'created_at', 'updated_at']
        read_only_fields = ['id', 'store', 'created_at', 'updated_at']