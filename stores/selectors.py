from django.db.models import QuerySet
from .models import Store


def get_user_stores(user) -> QuerySet:
    """
    Get all stores for a given user (Multi-Tenant Isolation).
    
    Args:
        user: The authenticated user object
        
    Returns:
        QuerySet of Store objects owned by the user
        
    Raises:
        None - returns empty QuerySet if user has no stores
    """
    return Store.objects.filter(
        tenant_id=user.tenant_id
    ).select_related('owner')
