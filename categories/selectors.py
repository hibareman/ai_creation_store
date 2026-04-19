from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count, Q
from .models import Category


def get_store_categories(store):
    """
    Retrieve all categories for a specific store.
    
    Args:
        store: Store instance
        
    Returns:
        QuerySet of Category objects filtered by store
        
    Raises:
        None - returns empty QuerySet if no categories
    """
    if not store:
        return Category.objects.none()
    
    return Category.objects.filter(
        store=store,
        tenant_id=store.tenant_id
    ).select_related('store').annotate(
        product_count=Count(
            'products',
            filter=Q(
                products__store_id=store.id,
                products__tenant_id=store.tenant_id,
            ),
        )
    ).order_by('created_at')


def get_category_by_id(category_id, store):
    """
    Retrieve a single category by ID with store ownership verification.
    
    Args:
        category_id: Category ID
        store: Store instance for ownership verification
        
    Returns:
        Category object if exists and belongs to store
        
    Raises:
        ObjectDoesNotExist: If category doesn't exist or doesn't belong to store
    """
    if not store:
        raise ObjectDoesNotExist("Store not found")
    
    return Category.objects.get(
        id=category_id,
        store=store,
        tenant_id=store.tenant_id
    )


def get_category_by_name(store, name):
    """
    Retrieve a category by name within a store scope.
    
    Used for duplicate name detection during creation/update.
    
    Args:
        store: Store instance
        name: Category name to search for
        
    Returns:
        Category object if exists, None otherwise
    """
    if not store or not name:
        return None
    
    try:
        return Category.objects.get(
            store=store,
            name=name,
            tenant_id=store.tenant_id
        )
    except Category.DoesNotExist:
        return None


def check_category_has_products(category):
    """
    Check if a category has linked products.

    Uses the real Product relation while enforcing same-store and same-tenant
    scope for safety.
    
    Args:
        category: Category instance
        
    Returns:
        Boolean: True if category has products, False otherwise
    """
    if not category:
        return False

    # Local import avoids hard coupling at module import time.
    from products.models import Product

    return Product.objects.filter(
        category=category,
        store_id=category.store_id,
        tenant_id=category.tenant_id,
    ).exists()
