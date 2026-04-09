from django.db import models
from django.conf import settings
from stores.models import Store
from categories.models import Category


def product_image_upload_path(instance, filename):
    """Generate a tenant-aware upload path for product images."""
    tenant_id = getattr(instance.product, 'tenant_id', 'unknown')
    store_id = getattr(instance.product, 'store_id', 'unknown')
    product_id = getattr(instance.product, 'id', 'unknown')
    return f'product_images/tenant_{tenant_id}/store_{store_id}/product_{product_id}/{filename}'


class Product(models.Model):
    """
    Product model representing a product in a store.
    
    MULTI-TENANT RULES:
    - Every product must have tenant_id for isolation
    - store_id is mandatory (FK to Store)
    - SKU must be unique per store (composite key with tenant_id)
    - All queries MUST filter by tenant_id and store_id
    """
    
    STATUS_CHOICES = (
        ("active", "Active"),
        ("inactive", "Inactive"),
    )
    
    # Basic product information
    id = models.AutoField(primary_key=True)
    name = models.CharField(
        max_length=255,
        help_text="Product name"
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text="Product description"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Product price"
    )
    sku = models.CharField(
        max_length=100,
        help_text="Stock Keeping Unit (unique per store)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
        help_text="Product status (active/inactive)"
    )
    
    # Foreign Keys
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='products',
        help_text="Store this product belongs to"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        help_text="Product category"
    )
    
    # MULTI-TENANT ISOLATION: Mandatory tenant_id
    tenant_id = models.IntegerField(
        null=False,
        blank=False,
        db_index=True,
        help_text="Tenant ID for multi-tenant isolation"
    )
    
    # Metadata
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Product creation timestamp"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Product last update timestamp"
    )
    
    class Meta:
        # MULTI-TENANT CONSTRAINT: SKU unique per store (composite with tenant_id)
        unique_together = [("store", "sku")]
        
        # PERFORMANCE OPTIMIZATION: Add indexes for filtering
        indexes = [
            models.Index(fields=['tenant_id']),
            models.Index(fields=['tenant_id', 'store']),
            models.Index(fields=['store', 'sku']),
            models.Index(fields=['status']),
        ]
        
        # ORDERING
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        """
        Override save to ensure tenant_id is set correctly.
        MULTI-TENANT RULE: tenant_id must be set from store.tenant_id
        """
        if not self.tenant_id:
            # Get tenant_id from store
            if self.store and self.store.tenant_id:
                self.tenant_id = self.store.tenant_id
            else:
                raise ValueError("Cannot save product: store.tenant_id is not set")
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.name} ({self.store.name})"


class ProductImage(models.Model):
    """
    ProductImage model representing images associated with a product.
    
    MULTI-TENANT RULES:
    - Inherits tenant_id from Product via FK
    - All queries MUST filter by product.tenant_id
    """
    
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        help_text="Product this image belongs to"
    )
    image_url = models.URLField(
        blank=True,
        default='',
        help_text="Image URL/path"
    )
    image_file = models.ImageField(
        upload_to=product_image_upload_path,
        blank=True,
        null=True,
        help_text="Uploaded product image file"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Image upload timestamp"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Image last update timestamp"
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        image_source = self.image_file.name if self.image_file else self.image_url
        return f"Image for {self.product.name} ({image_source})"


class Inventory(models.Model):
    """
    Inventory model representing stock levels of a product.
    
    MULTI-TENANT RULES:
    - Inherits tenant_id from Product via FK
    - One-to-One relationship with Product
    - All queries MUST filter by product.tenant_id
    """
    
    id = models.AutoField(primary_key=True)
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='inventory',
        help_text="Product this inventory belongs to"
    )
    stock_quantity = models.IntegerField(
        default=0,
        help_text="Current stock quantity"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Inventory creation timestamp"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Inventory last update timestamp"
    )
    
    class Meta:
        verbose_name_plural = "Inventories"
    
    def __str__(self):
        return f"Inventory: {self.product.name} ({self.stock_quantity})"
