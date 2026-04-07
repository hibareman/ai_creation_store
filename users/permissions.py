from rest_framework import permissions

class TenantAuthenticated(permissions.BasePermission):
    """
    Permission class ensures:
    1. User موجود ومصرح.
    2. للعمليات على Store، التحقق من أن المستخدم يمتلك المتجر.
    """
    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated)
    
    def has_object_permission(self, request, view, obj):
        """Verify that the user owns the store being accessed."""
        user = request.user
        # التحقق من أن المستخدم يمتلك المتجر
        return obj.owner_id == user.id