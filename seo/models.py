from django.db import models

from categories.models import Category
from products.models import Product
from stores.models import Store


class BaseSEOModel(models.Model):
    """Base abstract model for SEO fields shared across all entities."""
    meta_title = models.CharField(max_length=255, blank=True, default="")
    meta_description = models.TextField(blank=True, default="")
    meta_keywords = models.CharField(max_length=255, blank=True, default="")
    og_title = models.CharField(max_length=255, blank=True, default="")
    og_description = models.TextField(blank=True, default="")
    og_image_url = models.URLField(blank=True, default="")
    canonical_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class StoreSEO(BaseSEOModel):
    """SEO configuration for a Store."""
    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name="seo")

    def __str__(self):
        return f"Store SEO ({self.store_id})"


class ProductSEO(BaseSEOModel):
    """SEO configuration for a Product."""
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="seo")

    def __str__(self):
        return f"Product SEO ({self.product_id})"


class CategorySEO(BaseSEOModel):
    """SEO configuration for a Category."""
    category = models.OneToOneField(Category, on_delete=models.CASCADE, related_name="seo")

    def __str__(self):
        return f"Category SEO ({self.category_id})"