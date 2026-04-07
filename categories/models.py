from django.db import models
from django.conf import settings
from stores.models import Store


class Category(models.Model):
    """
    Category model for organizing products within a store.
    
    Each category belongs to exactly one store and must have a unique name
    within that store. Categories are part of the store's multi-tenant context.
    """
    
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='categories',
        help_text="Store this category belongs to"
    )
    
    # Denormalized tenant_id for efficient filtering and indexing
    tenant_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Tenant ID for multi-tenant isolation"
    )
    
    name = models.CharField(
        max_length=100,
        help_text="Category name (unique within store)"
    )
    
    description = models.TextField(
        blank=True,
        default='',
        help_text="Optional category description"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when category was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when category was last updated"
    )

    class Meta:
        # Composite unique constraint: name is unique per store
        unique_together = [('store', 'name')]
        
        # Indexes for efficient querying
        indexes = [
            models.Index(fields=['tenant_id']),
            models.Index(fields=['store']),
            models.Index(fields=['tenant_id', 'store']),
            models.Index(fields=['store', 'name']),
        ]
        
        ordering = ['created_at']
        verbose_name_plural = "Categories"

    def save(self, *args, **kwargs):
        """
        Override save to ensure tenant_id is always set.
        Tenant ID is derived from the store's tenant_id.
        """
        # Ensure tenant_id is never None (critical for multi-tenant)
        if not self.tenant_id and self.store_id:
            self.tenant_id = self.store.tenant_id
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} (Store: {self.store.name})"
