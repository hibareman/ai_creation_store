from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth import get_user_model
from django.http import JsonResponse

User = get_user_model()


class JWTTenantMiddleware(MiddlewareMixin):
    """
    Middleware لفك تشفير JWT وإضافة user + tenant_id لكل request
    مع التحقق من العزل بين المتاجر (Multi-Tenant)
    """

    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)

    def process_request(self, request):

        auth_header = request.META.get('HTTP_AUTHORIZATION', None)

        if not auth_header:
            request.tenant_id = None

            existing_user = getattr(request, 'user', None)
            if existing_user and getattr(existing_user, 'is_authenticated', False):
                request.tenant_id = getattr(existing_user, 'tenant_id', None)
                return

            tenant_id_header = request.META.get('HTTP_X_TENANT_ID')
            if tenant_id_header:
                try:
                    request.tenant_id = int(tenant_id_header)
                except (TypeError, ValueError):
                    return JsonResponse({'detail': 'Invalid tenant header.'}, status=400)
            return

        try:
            token_str = auth_header.split(' ')[1] if ' ' in auth_header else auth_header

            validated_token = UntypedToken(token_str)

            jwt_auth = JWTAuthentication()

            user = jwt_auth.get_user(validated_token)

            if not user.is_active:
                return JsonResponse({'detail': 'User inactive or deleted.'}, status=403)

            request.user = user

            request.tenant_id = getattr(user, 'tenant_id', None)

            # السماح لـ Super Admin بدون tenant_id
            if request.tenant_id is None and getattr(user, 'role', None) != 'Super Admin':
                return JsonResponse({'detail': 'tenant_id missing in token/user.'}, status=403)

        except (InvalidToken, TokenError):
            return JsonResponse({'detail': 'Invalid token.'}, status=401)

        except Exception:
            return JsonResponse({'detail': 'Authentication failed.'}, status=401)