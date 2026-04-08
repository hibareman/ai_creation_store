import logging
from django.db import DatabaseError, IntegrityError
from django.core.mail import send_mail
from django.conf import settings
from .models import User
from rest_framework_simplejwt.tokens import RefreshToken
import uuid

logger = logging.getLogger(__name__)


def register_user(username, email, password, role='Store Owner', tenant_id=None):
    """
    Register a new user with activation token.
    """
    try:
        user = User(
            username=username,
            email=email,
            role=role,
            is_active=False,
            activation_token=uuid.uuid4(),
        )

        user.set_password(password)
        user.save()

        if tenant_id is None:
            user.tenant_id = user.id
            user.save(update_fields=['tenant_id'])
        else:
            user.tenant_id = tenant_id
            user.save(update_fields=['tenant_id'])

        logger.info(f"User '{username}' registered successfully")
        return user

    except IntegrityError as e:
        logger.warning(f"Registration failed: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise


def login_user(user):
    """Generate JWT tokens for the given user."""
    try:
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user_id': user.id,
            'role': user.role,
            'tenant_id': getattr(user, 'tenant_id', None),
        }
    except Exception as e:
        logger.error(f"Failed to generate tokens: {str(e)}")
        raise


def activate_user_by_token(activation_token):
    """
    Activate user using UUID token.
    """
    try:
        user = User.objects.get(activation_token=activation_token, is_active=False)
        user.is_active = True
        user.activation_token = None  # مسح التوكن بعد التفعيل
        user.save(update_fields=['is_active', 'activation_token'])
        
        logger.info(f"User {user.email} activated successfully")
        return user
    except User.DoesNotExist:
        logger.warning(f"Invalid activation token: {activation_token}")
        raise Exception("Invalid activation token")


def send_activation_email(user):
    """Send activation email with simple link."""
    subject = "Activate your account"
    activation_link = f"http://localhost:8000/api/auth/activate/{user.activation_token}/"
    
    message = f"""
Hi {user.username},

Click the link below to activate your account:

{activation_link}

This link can only be used once.

-- 
Support Team"""
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        logger.info(f"Activation email sent to {user.email}")
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        raise