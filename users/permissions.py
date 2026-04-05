from rest_framework import permissions


class TenantAuthenticated(permissions.BasePermission):

    def has_permission(self, request, view):

        user = getattr(request, 'user', None)
        tenant_id = getattr(request, 'tenant_id', None)

        return bool(user and user.is_authenticated and tenant_id is not None)