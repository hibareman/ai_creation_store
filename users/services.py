import logging
from django.db import DatabaseError, IntegrityError
from .models import User
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)

def register_user(username, email, password, role='Store Owner', tenant_id=None):
    """
    Register a new user with the given credentials.
    
    Args:
        username: Username for the new user
        email: Email address
        password: User password
        role: User role (default: 'Store Owner')
        tenant_id: Tenant ID (default: None, set to user_id)
    
    Returns:
        User instance if registration successful, None if failed
    
    Raises:
        IntegrityError: If username or email already exists
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        user = User(
            username=username,
            email=email,
            role=role,
        )

        user.set_password(password)
        user.save()

        if tenant_id is None:
            user.tenant_id = user.id
            user.save(update_fields=['tenant_id'])
        else:
            user.tenant_id = tenant_id
            user.save(update_fields=['tenant_id'])

        logger.info(f"User '{username}' registered successfully with role '{role}' and tenant_id {user.tenant_id}")
        return user
    
    except IntegrityError as e:
        logger.warning(f"Registration failed for username '{username}': Username or email already exists - {str(e)}")
        raise
    except DatabaseError as e:
        logger.error(f"Database error during registration for username '{username}': {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during registration for username '{username}': {str(e)}")
        raise


def login_user(user):
    """
    Generate JWT tokens for the given user.
    
    Args:
        user: User instance
    
    Returns:
        Dictionary with access token, refresh token, and user info
    
    Raises:
        Exception: If token generation fails (re-raised after logging)
    """
    try:
        refresh = RefreshToken.for_user(user)
        
        logger.info(f"User '{user.username}' (id: {user.id}, tenant_id: {getattr(user, 'tenant_id', None)}) logged in successfully")
        
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user_id': user.id,
            'role': user.role,
            'tenant_id': getattr(user, 'tenant_id', None),
        }
    
    except Exception as e:
        logger.error(f"Failed to generate tokens for user '{user.username}' (id: {user.id}): {str(e)}")
        raise