"""
Serializers for Products API

RULE: Serializers should only validate data format, not business logic.
Business logic belongs in services.py.

This version only changes the external response DTOs:
- Unified product DTO for list/detail/create/update responses
- Unified image DTO with final display-ready image_url
- No business-logic changes
"""

from rest_framework import serializers
from PIL import Image, UnidentifiedImageError

from categories.models import Category
from .models import Product, ProductImage, Inventory


class InventorySerializer(serializers.ModelSerializer):
    """
    Serializer for Inventory model.
    """

    class Meta:
        model = Inventory
        fields = ["id", "stock_quantity", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "stock_quantity": {
                "help_text": "Current stock quantity (minimum 0)",
                "min_value": 0,
            },
        }


class ProductImageSerializer(serializers.ModelSerializer):
    """
    Unified image DTO for both list/create responses.

    Response shape:
    {
        "id": 1,
        "image_url": "http://localhost:8000/media/...",
        "created_at": "...",
        "updated_at": "..."
    }

    Request still supports:
    - image_file (multipart upload)
    - image_url
    """

    image_url = serializers.SerializerMethodField(
        help_text="Final display-ready image URL"
    )
    image_file = serializers.ImageField(
        required=False,
        allow_null=True,
        write_only=True,
        use_url=True,
        help_text="Upload product image (PNG, JPG, GIF, WEBP)"
    )

    MAX_IMAGE_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}

    class Meta:
        model = ProductImage
        fields = ["id", "image_url", "image_file", "created_at", "updated_at"]
        read_only_fields = ["id", "image_url", "created_at", "updated_at"]

    def get_image_url(self, obj):
        """
        Always expose a final, display-ready URL.
        Prefer uploaded file URL; fall back to stored image_url.
        """
        if obj.image_file:
            try:
                url = obj.image_file.url
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(url)
                return url
            except Exception:
                pass

        return obj.image_url or None

    def validate_image_file(self, value):
        """
        Validate uploaded image file type/format and size.
        """
        if value is None:
            return value

        if value.size > self.MAX_IMAGE_FILE_SIZE:
            raise serializers.ValidationError(
                "Image file too large. Maximum allowed size is 5 MB."
            )

        content_type = getattr(value, "content_type", "")
        if content_type and not content_type.startswith("image/"):
            raise serializers.ValidationError(
                "Unsupported file type. Only image uploads are allowed."
            )

        try:
            value.seek(0)
            with Image.open(value) as img:
                image_format = (img.format or "").upper()
                img.verify()
        except (UnidentifiedImageError, OSError):
            raise serializers.ValidationError(
                "Invalid image file. Please upload a valid image."
            )
        finally:
            value.seek(0)

        if image_format not in self.ALLOWED_IMAGE_FORMATS:
            allowed_formats = ", ".join(sorted(self.ALLOWED_IMAGE_FORMATS))
            raise serializers.ValidationError(
                f"Unsupported image format '{image_format}'. Allowed formats: {allowed_formats}."
            )

        return value


class ProductResponseSerializer(serializers.ModelSerializer):
    """
    Unified product DTO used for:
    - GET list
    - GET detail
    - POST response
    - PUT response
    - PATCH response

    Response shape:
    {
      "id": 1,
      "store_id": 1,
      "category_id": 1,
      "category_name": "phones",
      "name": "Wireless Mouse",
      "description": "Bluetooth mouse",
      "price": 25.99,
      "sku": "MOUSE-BT-001",
      "stock": 0,
      "status": "active",
      "image_url": null,
      "created_at": "...",
      "updated_at": "..."
    }
    """

    store_id = serializers.IntegerField(
        read_only=True,
        help_text="Store ID this product belongs to"
    )
    category_id = serializers.IntegerField(
        read_only=True,
        help_text="Category ID"
    )
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
        help_text="Category name"
    )
    price = serializers.SerializerMethodField(
        help_text="Product price as numeric value"
    )
    stock = serializers.SerializerMethodField(
        help_text="Current stock quantity"
    )
    image_url = serializers.SerializerMethodField(
        help_text="Primary product image URL"
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "store_id",
            "category_id",
            "category_name",
            "name",
            "description",
            "price",
            "sku",
            "stock",
            "status",
            "image_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "store_id",
            "category_id",
            "category_name",
            "stock",
            "image_url",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {"help_text": "Product name"},
            "description": {"help_text": "Product description"},
            "price": {"help_text": "Product price (numeric)"},
            "sku": {"help_text": "Stock Keeping Unit - unique per store"},
            "status": {"help_text": "Status: active, draft, out_of_stock"},
        }

    def get_stock(self, obj):
        try:
            return int(getattr(obj.inventory, "stock_quantity", 0) or 0)
        except Inventory.DoesNotExist:
            return 0

    def get_price(self, obj):
        if obj.price is None:
            return None
        return float(obj.price)

    def get_image_url(self, obj):
        prefetched_images = getattr(obj, "_prefetched_objects_cache", {}).get("images")
        if prefetched_images is None:
            image = obj.images.order_by("-created_at").first()
        else:
            image = prefetched_images[0] if prefetched_images else None

        if not image:
            return None

        if image.image_file:
            try:
                url = image.image_file.url
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(url)
                return url
            except Exception:
                return None

        return image.image_url or None


class ProductListSerializer(ProductResponseSerializer):
    """
    Keep existing name for compatibility with current views/imports.
    """
    pass


class ProductDetailSerializer(ProductResponseSerializer):
    """
    Keep existing name for compatibility with current views/imports.

    Detail now returns the same unified flat DTO as list/create/update,
    as requested by frontend.
    """
    pass


class ProductCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating products.

    Request support remains unchanged in logic:
    - name
    - description
    - price
    - stock
    - status
    - category_id
    - image_url
    - sku
    - category (legacy field still supported)
    """

    category_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text="Category ID"
    )
    stock = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        write_only=True,
        help_text="Initial stock quantity"
    )
    image_url = serializers.URLField(
        required=False,
        allow_null=True,
        allow_blank=True,
        write_only=True,
        help_text="Primary image URL"
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "description",
            "price",
            "stock",
            "status",
            "category_id",
            "image_url",
            "sku",
            "category",
        ]
        extra_kwargs = {
            "name": {
                "help_text": "Product name (required)",
                "required": True,
                "max_length": 255,
            },
            "description": {
                "help_text": "Product description",
                "required": False,
            },
            "price": {
                "help_text": "Product price (must be > 0)",
                "decimal_places": 2,
            },
            "sku": {
                "help_text": "Stock Keeping Unit",
                "required": False,
                "max_length": 100,
            },
            "status": {
                "help_text": "Product status: active, draft, out_of_stock",
                "default": "active",
            },
            "category": {
                "help_text": "Category ID (legacy field, prefer category_id)",
                "required": False,
            },
        }

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value

    def validate_sku(self, value):
        if value is None:
            return None
        if not value.strip():
            return None
        return value.strip().upper()

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Product name is required")
        return value.strip()

    def validate(self, attrs):
        category = attrs.get("category")
        category_id_provided = "category_id" in attrs
        category_id = attrs.pop("category_id", None)

        if category_id_provided:
            if category_id is None:
                attrs["category"] = None
            else:
                try:
                    resolved_category = Category.objects.get(id=category_id)
                except Category.DoesNotExist:
                    raise serializers.ValidationError({"category_id": "Invalid category_id"})

                if category is not None and category.id != resolved_category.id:
                    raise serializers.ValidationError(
                        {"category_id": "category_id does not match category"}
                    )
                attrs["category"] = resolved_category

        return attrs


class ProductUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating products.

    Logic remains unchanged.
    """

    category_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text="Category ID"
    )

    class Meta:
        model = Product
        fields = ["name", "description", "price", "sku", "status", "category", "category_id"]
        extra_kwargs = {
            "name": {
                "help_text": "Product name",
                "required": False,
                "max_length": 255,
            },
            "description": {
                "help_text": "Product description",
                "required": False,
            },
            "price": {
                "help_text": "Product price (must be > 0 if provided)",
                "required": False,
                "decimal_places": 2,
            },
            "sku": {
                "help_text": "Stock Keeping Unit",
                "required": False,
                "max_length": 100,
            },
            "status": {
                "help_text": "Product status: active, draft, out_of_stock",
                "required": False,
            },
            "category": {
                "help_text": "Category ID",
                "required": False,
            },
        }

    def validate_price(self, value):
        if value and value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value

    def validate_sku(self, value):
        if value and (not value.strip()):
            raise serializers.ValidationError("SKU cannot be empty")
        return value.strip().upper() if value else value

    def validate_name(self, value):
        if value and not value.strip():
            raise serializers.ValidationError("Product name cannot be empty")
        return value.strip() if value else value

    def validate(self, attrs):
        category = attrs.get("category")
        category_id_provided = "category_id" in attrs
        category_id = attrs.pop("category_id", None)

        if category_id_provided:
            if category_id is None:
                attrs["category"] = None
            else:
                try:
                    resolved_category = Category.objects.get(id=category_id)
                except Category.DoesNotExist:
                    raise serializers.ValidationError({"category_id": "Invalid category_id"})

                if category is not None and category.id != resolved_category.id:
                    raise serializers.ValidationError(
                        {"category_id": "category_id does not match category"}
                    )
                attrs["category"] = resolved_category

        return attrs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.partial:
            for field_name in ["name", "description", "price", "sku", "status"]:
                self.fields[field_name].required = True


class InventoryUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating inventory stock.
    """

    class Meta:
        model = Inventory
        fields = ["stock_quantity"]
        extra_kwargs = {
            "stock_quantity": {
                "help_text": "Stock quantity (must be >= 0)",
                "min_value": 0,
            },
        }

    def validate_stock_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError("Stock quantity cannot be negative")
        return value


class PublicProductListSerializer(serializers.ModelSerializer):
    """Public-safe product list representation."""

    class Meta:
        model = Product
        fields = ["id", "name", "price"]


class PublicProductDetailSerializer(serializers.ModelSerializer):
    """Public-safe product detail representation."""

    class Meta:
        model = Product
        fields = ["id", "name", "description", "price"]
