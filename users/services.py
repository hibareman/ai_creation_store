import logging
from django.db import DatabaseError, IntegrityError
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.core.mail import send_mail
from django.conf import settings
from .models import User
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)


def register_user(username, email, password, role='Store Owner', tenant_id=None):
    """
    Register a new user with the given credentials. User is created inactive and
    requires email activation.

    Returns the created User instance.
    """
    try:
        user = User(
            username=username,
            email=email,
            role=role,
            is_active=False,
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


def generate_activation_token(user):
    """Return a timestamp-signed token for the given user id."""
    signer = TimestampSigner()
    return signer.sign(str(user.id))


def activate_user(token, max_age_seconds=7 * 24 * 3600):
    """
    Validate activation token and activate the user. Returns the user instance.
    Raises BadSignature or SignatureExpired on invalid tokens.
    """
    signer = TimestampSigner()
    try:
        unsigned = signer.unsign(token, max_age=max_age_seconds)
        user_id = int(unsigned)
        user = User.objects.get(pk=user_id)

        user.is_active = True
        if not getattr(user, 'tenant_id', None):
            user.tenant_id = user.id
        user.save(update_fields=['is_active', 'tenant_id'])

        logger.info(f"Activated user id={user.id}")
        return user

    except SignatureExpired:
        logger.warning("Activation token expired")
        raise
    except BadSignature:
        logger.warning("Invalid activation token")
        raise


def send_activation_email(user, activation_url):
    """Send activation email with the given activation_url. Uses configured EMAIL_BACKEND."""
    subject = "Activate your account"
    message = f"Hi {user.username},\n\nPlease activate your account by visiting the following link:\n{activation_url}\n\nThis link expires in 7 days.\n"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')
    try:
        send_mail(subject, message, from_email, [user.email], fail_silently=False)
        logger.info(f"Sent activation email to {user.email}")
    except Exception as e:
        logger.error(f"Failed to send activation email to {user.email}: {e}")
        raise