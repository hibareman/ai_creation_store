from django.db.models import QuerySet
from .models import Store, StoreDomain


def get_user_stores(user) -> QuerySet:
    """
    Get all stores for a given user (Multi-Tenant Isolation).
    Returns only stores owned by the user within the user's tenant_id.
    
    Args:
        user: The authenticated user object
        
    Returns:
        QuerySet of Store objects owned by the user in their tenant
        
    Raises:
        None - returns empty QuerySet if user has no tenant_id
    """
    # Critical: Check if user has valid tenant_id
    if not getattr(user, 'tenant_id', None):
        return Store.objects.none()
    
    return Store.objects.filter(
        tenant_id=user.tenant_id,
        owner_id=user.id,
    ).select_related('owner')


def get_store_by_id(store_id: int):
    """
    Get a store by ID.

    Returns:
        Store instance or None if not found.
    """
    return Store.objects.filter(id=store_id).first()


def get_store_domains_by_store_id(store_id: int) -> QuerySet:
    """
    Get domains for a specific store.
    """
    return StoreDomain.objects.filter(store_id=store_id)
