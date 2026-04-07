from django.db.models import QuerySet
from .models import Store


def get_user_stores(user) -> QuerySet:
    """
    Get all stores for a given user (Multi-Tenant Isolation).
    Returns only stores within the user's tenant_id.
    
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
        tenant_id=user.tenant_id
    ).select_related('owner')
