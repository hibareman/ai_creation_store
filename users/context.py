def get_current_tenant(request):
    """
    إرجاع tenant_id من الـ request.
    """
    return getattr(request, 'tenant_id', None)


def get_current_user(request):
    """
    إرجاع المستخدم الحالي من الـ request.
    """
    return getattr(request, 'user', None)
