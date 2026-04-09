"""
Serializers for Products API

RULE: Serializers should only validate data format, not business logic
Business logic belongs in services.py
"""

from rest_framework import serializers
from .models import Product, ProductImage, Inventory


class InventorySerializer(serializers.ModelSerializer):
    """
    Serializer for Inventory model.
    
    **Purpose:** Track product stock quantities
    
    **Fields:**
    - id: Inventory record ID (read-only)
    - stock_quantity: Current stock level
    - created_at, updated_at: Timestamps (read-only)
    """
    
    class Meta:
        model = Inventory
        fields = ['id', 'stock_quantity', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'stock_quantity': {
                'help_text': 'Current stock quantity (minimum 0)',
                'min_value': 0,
            },
        }


class ProductImageSerializer(serializers.ModelSerializer):
    """
    Serializer for ProductImage model.
    
    **Purpose:** Manage product gallery images
    
    **Fields:**
    - id: Image record ID (read-only)
    - image_url: URL of uploaded image
    - image_file: Upload new image file
    - created_at, updated_at: Timestamps (read-only)
    """
    image_file = serializers.ImageField(
        required=False,
        allow_null=True,
        use_url=True,
        help_text='Upload product image (PNG, JPG, GIF)'
    )
    
    class Meta:
        model = ProductImage
        fields = ['id', 'image_url', 'image_file', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'image_url': {
                'help_text': 'URL of the uploaded image',
            },
        }


class ProductListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing products (lightweight).
    
    **Purpose:** List all products in store with minimal data
    
    **Includes:**
    - Basic product info (name, price, SKU)
    - Category name (nested)
    - Inventory status
    
    **Optimized:** Uses select_related for category and prefetch_related for inventory
    """
    
    category_name = serializers.CharField(
        source='category.name',
        read_only=True,
        help_text='Category name'
    )
    inventory = InventorySerializer(
        read_only=True,
        help_text='Product inventory/stock information'
    )
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'price', 'sku', 'status', 'category_name', 'inventory', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'category_name']
        extra_kwargs = {
            'name': {'help_text': 'Product name'},
            'price': {'help_text': 'Product price (currency from store settings)'},
            'sku': {'help_text': 'Stock Keeping Unit - unique per store'},
            'status': {'help_text': 'Status: active, inactive, archived'},
        }


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for product detail view.
    
    **Purpose:** Full product information with images and inventory
    
    **Includes:**
    - All product details
    - Gallery images
    - Inventory/stock information
    - Store reference
    
    **Nested:**
    - category_name: From related Category
    - images: ProductImageSerializer (many=True)
    - inventory: InventorySerializer
    """
    
    category_name = serializers.CharField(
        source='category.name',
        read_only=True,
        help_text='Category name'
    )
    images = ProductImageSerializer(
        many=True,
        read_only=True,
        help_text='Product images/gallery'
    )
    inventory = InventorySerializer(
        read_only=True,
        help_text='Current inventory status'
    )
    store_id = serializers.IntegerField(
        read_only=True,
        help_text='Store ID this product belongs to'
    )
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 'sku', 'status',
            'category_name', 'store_id', 'images', 'inventory',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'store_id', 'created_at', 'updated_at', 'images', 'inventory']
        extra_kwargs = {
            'name': {
                'help_text': 'Product name (required)',
                'max_length': 255,
            },
            'description': {
                'help_text': 'Product description',
                'required': False,
            },
            'price': {
                'help_text': 'Product price (must be > 0)',
                'decimal_places': 2,
            },
            'sku': {
                'help_text': 'Stock Keeping Unit (unique per store)',
                'max_length': 100,
            },
            'status': {
                'help_text': 'Product status: active, inactive, archived',
                'default': 'active',
            },
        }


class ProductCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating products.
    
    **Purpose:** Validate new product creation
    
    **Required Fields:**
    - name: Product name
    - category: Category ID
    
    **Optional Fields:**
    - description: Product description
    - price: Default 0.00
    - sku: Generated from name if not provided
    - status: Default 'active'
    
    **Validations:**
    - Price must be > 0
    - SKU cannot be empty
    - Name cannot be empty
    """
    
    class Meta:
        model = Product
        fields = ['name', 'description', 'price', 'sku', 'status', 'category']
        extra_kwargs = {
            'name': {
                'help_text': 'Product name (required)',
                'required': True,
                'max_length': 255,
            },
            'description': {
                'help_text': 'Product description',
                'required': False,
            },
            'price': {
                'help_text': 'Product price (must be > 0)',
                'decimal_places': 2,
            },
            'sku': {
                'help_text': 'Stock Keeping Unit',
                'required': True,
                'max_length': 100,
            },
            'status': {
                'help_text': 'Product status',
                'default': 'active',
            },
            'category': {
                'help_text': 'Category ID',
                'required': True,
            },
        }
        
    def validate_price(self, value):
        """Price must be positive"""
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value
    
    def validate_sku(self, value):
        """SKU must not be empty"""
        if not value or not value.strip():
            raise serializers.ValidationError("SKU cannot be empty")
        return value.strip().upper()
    
    def validate_name(self, value):
        """Name must not be empty"""
        if not value or not value.strip():
            raise serializers.ValidationError("Product name is required")
        return value.strip()


class ProductUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating products.
    
    **Purpose:** Validate product updates
    
    **All Fields Optional:** Supports partial updates
    
    **Validations:**
    - Price: Must be > 0 if provided
    - SKU: Cannot be empty if provided
    - Name: Cannot be empty if provided
    """
    
    class Meta:
        model = Product
        fields = ['name', 'description', 'price', 'sku', 'status', 'category']
        extra_kwargs = {
            'name': {
                'help_text': 'Product name',
                'required': False,
                'max_length': 255,
            },
            'description': {
                'help_text': 'Product description',
                'required': False,
            },
            'price': {
                'help_text': 'Product price (must be > 0 if provided)',
                'required': False,
                'decimal_places': 2,
            },
            'sku': {
                'help_text': 'Stock Keeping Unit',
                'required': False,
                'max_length': 100,
            },
            'status': {
                'help_text': 'Product status',
                'required': False,
            },
            'category': {
                'help_text': 'Category ID',
                'required': False,
            },
        }
    
    def validate_price(self, value):
        """Price must be positive"""
        if value and value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value
    
    def validate_sku(self, value):
        """SKU must not be empty"""
        if value and (not value.strip()):
            raise serializers.ValidationError("SKU cannot be empty")
        return value.strip().upper() if value else value
    
    def validate_name(self, value):
        """Name must not be empty"""
        if value and not value.strip():
            raise serializers.ValidationError("Product name cannot be empty")
        return value.strip() if value else value


class InventoryUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating inventory stock.
    
    **Purpose:** Update product stock quantities
    
    **Fields:**
    - stock_quantity: Current available stock (must be >= 0)
    
    **Validations:**
    - Stock cannot be negative
    - Integer values only
    """
    
    class Meta:
        model = Inventory
        fields = ['stock_quantity']
        extra_kwargs = {
            'stock_quantity': {
                'help_text': 'Stock quantity (must be >= 0)',
                'min_value': 0,
            },
        }
    
    def validate_stock_quantity(self, value):
        """Stock quantity must be >= 0"""
        if value < 0:
            raise serializers.ValidationError("Stock quantity cannot be negative")
        return value
