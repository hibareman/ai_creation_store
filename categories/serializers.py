from rest_framework import serializers
from .models import Category


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer for Category model.
    
    Used for both read and write operations. Validates:
    - Required fields (name)
    - String length constraints
    - Unique constraint on (store, name)
    """
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_name(self, value):
        """
        Validate category name:
        - Non-empty
        - Max length checked by model
        """
        if not value or not value.strip():
            raise serializers.ValidationError("Category name is required and cannot be empty")
        return value.strip()
    
    def validate_description(self, value):
        """
        Validate and clean description field.
        """
        if value is None:
            return ''
        return value.strip() if isinstance(value, str) else ''


class CategoryCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Specialized serializer for create/update operations.
    
    Enforces all required validations including:
    - Name uniqueness within store
    - Required name field
    """
    
    class Meta:
        model = Category
        fields = ['name', 'description']
    
    def validate_name(self, value):
        """
        Validate category name:
        - Non-empty
        - Unique within the store context
        """
        if not value or not value.strip():
            raise serializers.ValidationError("Category name is required and cannot be empty")
        return value.strip()
    
    def validate_description(self, value):
        """
        Validate and clean description field.
        """
        if value is None:
            return ''
        return value.strip() if isinstance(value, str) else ''
    
    def validate(self, attrs):
        """
        Perform cross-field validation.
        
        Checks:
        - Name uniqueness within the store (for create, or excluding self for update)
        """
        # Store is provided by the view context
        request = self.context.get('request')
        store = self.context.get('store')
        
        if not store:
            raise serializers.ValidationError("Store context is required")
        
        name = attrs.get('name')
        
        if name:
            # For update operations, exclude current instance
            queryset = Category.objects.filter(store=store, name=name)
            
            if self.instance:
                queryset = queryset.exclude(id=self.instance.id)
            
            if queryset.exists():
                raise serializers.ValidationError(
                    {"name": f"Category '{name}' already exists in this store"}
                )
        
        return attrs
