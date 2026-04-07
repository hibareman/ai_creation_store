from rest_framework import permissions

class TenantAuthenticated(permissions.BasePermission):
    """
    Permission class ensures:
    1. User موجود ومصرح.
    2. للعمليات على Store، التحقق من أن المستخدم يمتلك المتجر وفي نفس الـ tenant.
    3. فرض العزل بين المستأجرين (Multi-Tenant Isolation).
    """
    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated)
    
    def has_object_permission(self, request, view, obj):
        """Verify that the user owns the store being accessed AND is in the same tenant."""
        user = request.user
        
        # Super Admin always has access
        if user.role == 'Super Admin':
            return True
        
        # Check if request has valid tenant_id
        tenant_id = getattr(request, 'tenant_id', None)
        if tenant_id is None:
            return False
        
        # Critical: Verify tenant_id matches (multi-tenant isolation)
        obj_tenant_id = None
        
        # Check if obj has tenant_id directly
        if hasattr(obj, 'tenant_id'):
            obj_tenant_id = obj.tenant_id
        # Check if obj is a Store's related object (e.g., StoreDomain, StoreSettings)
        elif hasattr(obj, 'store') and hasattr(obj.store, 'tenant_id'):
            obj_tenant_id = obj.store.tenant_id
        else:
            return False
        
        if obj_tenant_id != tenant_id:
            return False
        
        # Then verify ownership
        if hasattr(obj, 'owner_id'):
            return obj.owner_id == user.id
        # Check if obj is related to a store owned by user
        elif hasattr(obj, 'store') and hasattr(obj.store, 'owner_id'):
            return obj.store.owner_id == user.id
        
        return False