from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
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
    ).select_related('store').order_by('created_at')


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
    
    This is a structural check - actual product relationship
    will be implemented when Product model is created.
    
    Args:
        category: Category instance
        
    Returns:
        Boolean: True if category has products, False otherwise
    """
    # Placeholder for future products relationship
    # When products are added: return category.products.exists()
    return False
