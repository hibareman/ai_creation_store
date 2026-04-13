"""
Selectors for Products - Data Access Layer

MULTI-TENANT RULE: 
Every query MUST be filtered by tenant_id and store_id
PROMPT: "قبل تنفيذ أي استعلام، تأكد أن الاستعلام محدود بـ tenant_id"
"""

from django.db.models import QuerySet, Prefetch
from .models import Product, ProductImage, Inventory


def get_product_by_id(product_id: int, store_id: int, tenant_id: int) -> Product:
    """
    Get a single product by ID with tenant/store isolation.
    
    MULTI-TENANT RULE: Verify ownership before returning
    Raises Product.DoesNotExist if not found or unauthorized
    """
    return Product.objects.select_related('category', 'store').prefetch_related('images').get(
        id=product_id,
        store_id=store_id,
        tenant_id=tenant_id
    )


def get_products_by_store(store_id: int, tenant_id: int) -> QuerySet:
    """
    Get all products for a specific store with tenant isolation.
    
    MULTI-TENANT RULE: Uses composite filter (tenant_id + store_id)
    Optimization: Uses select_related and prefetch_related
    """
    return Product.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id
    ).select_related(
        'category', 'store'
    ).prefetch_related(
        'images', 'inventory'
    ).order_by('-created_at')


def get_product_images(product_id: int, store_id: int, tenant_id: int) -> QuerySet:
    """
    Get all images for a product with tenant isolation.
    
    MULTI-TENANT RULE: Verify product ownership first
    """
    # Verify product belongs to this store/tenant
    Product.objects.get(
        id=product_id,
        store_id=store_id,
        tenant_id=tenant_id
    )
    
    return ProductImage.objects.filter(
        product_id=product_id
    ).order_by('-created_at')


def get_product_by_sku(sku: str, store_id: int, tenant_id: int) -> Product:
    """
    Get product by SKU with tenant/store isolation.
    
    MULTI-TENANT RULE: SKU is unique per store (composite key)
    """
    return Product.objects.select_related('category', 'store').prefetch_related('images').get(
        sku=sku,
        store_id=store_id,
        tenant_id=tenant_id
    )


def get_inventory_for_product(product_id: int, store_id: int, tenant_id: int) -> Inventory:
    """
    Get inventory record for a product with tenant isolation.
    
    MULTI-TENANT RULE: Verify product ownership first
    """
    # Verify product belongs to this store/tenant
    product = Product.objects.get(
        id=product_id,
        store_id=store_id,
        tenant_id=tenant_id
    )
    
    return product.inventory


def get_active_products_by_store(store_id: int, tenant_id: int) -> QuerySet:
    """
    Get only active products for a store.
    """
    return Product.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
        status='active'
    ).select_related(
        'category', 'store'
    ).prefetch_related(
        'images', 'inventory'
    ).order_by('-created_at')


def get_products_by_category(category_id: int, store_id: int, tenant_id: int) -> QuerySet:
    """
    Get all products in a specific category with tenant isolation.
    
    MULTI-TENANT RULE: Verify category belongs to store first
    """
    return Product.objects.filter(
        category_id=category_id,
        store_id=store_id,
        tenant_id=tenant_id
    ).select_related(
        'category', 'store'
    ).prefetch_related(
        'images', 'inventory'
    ).order_by('-created_at')
