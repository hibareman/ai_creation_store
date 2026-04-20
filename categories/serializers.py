from rest_framework import serializers
from .models import Category


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer for Category model - Full operations.
    
    **Purpose:** Read and write categories within a store
    
    **Multi-Tenant:** Categories are scoped to store_id automatically
    
    **Fields:**
    - id: Auto-generated category ID
    - name: Category display name (required, unique per store)
    - description: Category description (optional)
    - created_at: Auto-managed creation timestamp
    - updated_at: Auto-managed modification timestamp
    
    **Validations:**
    - Name: Required, non-empty, max 255 characters
    - Name uniqueness: Enforced per store
    - Description: Optional, cleaned whitespace
    """
    
    store_id = serializers.IntegerField(read_only=True)
    image_url = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id',
            'store_id',
            'name',
            'description',
            'image_url',
            'product_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'store_id',
            'image_url',
            'product_count',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'name': {
                'help_text': 'Category name (must be unique per store)',
                'max_length': 255,
            },
            'description': {
                'help_text': 'Category description',
                'required': False,
            },
        }

    def get_image_url(self, obj):
        """
        Placeholder field for frontend contract compatibility.
        Category currently does not store an image, so this returns null.
        """
        return None

    def get_product_count(self, obj):
        """
        Return linked products count.
        Uses annotated value when available to avoid extra queries.
        """
        annotated_count = getattr(obj, 'product_count', None)
        if annotated_count is not None:
            try:
                return int(annotated_count)
            except (TypeError, ValueError):
                pass
        return obj.products.count()
    
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
    
    **Purpose:** Enforce validation for write operations
    
    **Enforces:**
    - Name uniqueness within store
    - Required name field
    - Description is optional
    """
    
    class Meta:
        model = Category
        fields = ['name', 'description']
        extra_kwargs = {
            'name': {
                'help_text': 'Category name (must be unique per store)',
                'max_length': 255,
                'required': True,
            },
            'description': {
                'help_text': 'Category description (optional)',
                'required': False,
            },
        }
    
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
