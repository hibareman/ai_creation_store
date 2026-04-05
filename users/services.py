from .models import User
from rest_framework_simplejwt.tokens import RefreshToken


def register_user(username, email, password, role='Store Owner', tenant_id=None):

    user = User(
        username=username,
        email=email,
        role=role,
    )

    if tenant_id:
        user.tenant_id = tenant_id

    user.set_password(password)
    user.save()

    return user


def login_user(user):

    refresh = RefreshToken.for_user(user)

    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user_id': user.id,
        'role': user.role,
        'tenant_id': getattr(user, 'tenant_id', None),
    }