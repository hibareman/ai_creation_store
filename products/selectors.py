"""
Selectors for Products - Data Access Layer

MULTI-TENANT RULE: 
Every query MUST be filtered by tenant_id and store_id
PROMPT: "قبل تنفيذ أي استعلام، تأكد أن الاستعلام محدود بـ tenant_id"
"""

from django.db.models import Q, QuerySet, Prefetch
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


def search_products(queryset: QuerySet, search: str) -> QuerySet:
    """Apply partial, case-insensitive name or SKU search to a scoped queryset."""
    if not search:
        return queryset

    return queryset.filter(
        Q(name__icontains=search) | Q(sku__icontains=search)
    )


def search_products_by_name(queryset: QuerySet, search: str) -> QuerySet:
    """Backward-compatible alias for the expanded product search."""
    return search_products(queryset, search)


def filter_products_by_category(queryset: QuerySet, category_id: int) -> QuerySet:
    """
    Apply category filtering to an already scoped queryset.
    """
    return queryset.filter(category_id=category_id)


def filter_products_by_status(queryset: QuerySet, status: str) -> QuerySet:
    """Apply product status filtering to an already scoped queryset."""
    return queryset.filter(status=status)


def filter_products_by_stock_status(queryset: QuerySet, stock_status: str) -> QuerySet:
    """Filter products by their current inventory availability."""
    if stock_status == "in_stock":
        return queryset.filter(inventory__stock_quantity__gt=0)

    # Products with no inventory row are also treated as out of stock.
    return queryset.filter(
        Q(inventory__stock_quantity__lte=0) | Q(inventory__isnull=True)
    )


def order_products(queryset: QuerySet, ordering: str) -> QuerySet:
    """Apply a validated ordering expression to a scoped product queryset."""
    return queryset.order_by(ordering)


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


def count_active_products_for_store(store_id: int, tenant_id: int) -> int:
    """
    Count active products for a store with strict tenant isolation.
    """
    return Product.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
        status='active'
    ).count()


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


def get_public_products_for_store(store) -> QuerySet:
    """
    Get publicly visible products for a published/active store.
    Query-only selector: scoped by store and tenant, filtered to active products.
    """
    return Product.objects.filter(
        store_id=store.id,
        tenant_id=store.tenant_id,
        status='active',
    ).order_by('-id')


def get_public_product_detail(store, product_id):
    """
    Get one publicly visible product for a published/active store.
    Query-only selector: scoped by store and tenant, filtered to active product.
    """
    return Product.objects.filter(
        id=product_id,
        store_id=store.id,
        tenant_id=store.tenant_id,
        status='active',
    ).first()
