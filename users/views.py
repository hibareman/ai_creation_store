from rest_framework import generics, status, serializers as drf_serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from .serializers import RegisterSerializer, LoginSerializer, CurrentUserSerializer
from .services import (
    register_user,
    login_user,
    send_activation_email,
    activate_user_by_token,
    get_auth_bootstrap_store_payload,
)

DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Bad request"),
    403: OpenApiResponse(description="Permission denied"),
    404: OpenApiResponse(description="Not found"),
}


@extend_schema_view(
    post=extend_schema(
        summary="Register user account",
        description="Create a new Store Owner account and send a one-time activation email.",
        tags=["Auth"],
        request=RegisterSerializer,
        examples=[
            OpenApiExample(
                name="Register Success",
                value={"detail": "Activation email sent. Please check your inbox."},
                response_only=True,
            ),
        ],
        responses={
            201: inline_serializer(
                name="RegisterSuccessResponse",
                fields={
                    "detail": drf_serializers.CharField(),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class RegisterView(generics.GenericAPIView):

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        user = register_user(
            username=data["username"],
            email=data["email"],
            password=data["password"],
            role=data.get("role", "Store Owner"),
        )

        send_activation_email(user)

        return Response({"detail": "Activation email sent. Please check your inbox."}, 
                       status=status.HTTP_201_CREATED)


@extend_schema_view(
    post=extend_schema(
        summary="Login with email and password",
        description="Authenticate user credentials and return JWT tokens plus user identity context.",
        tags=["Auth"],
        request=LoginSerializer,
        examples=[
            OpenApiExample(
                name="Login Success",
                value={
                    "access": "<jwt-access-token>",
                    "refresh": "<jwt-refresh-token>",
                    "user_id": 12,
                    "role": "Store Owner",
                    "tenant_id": 12,
                    "stores": [
                        {
                            "id": 1,
                            "name": "My Store",
                            "slug": "my-store",
                            "subdomain": "my-store",
                        }
                    ],
                    "current_store": {
                        "id": 1,
                        "name": "My Store",
                        "slug": "my-store",
                        "subdomain": "my-store",
                    },
                },
                response_only=True,
            ),
        ],
        responses={
            200: inline_serializer(
                name="LoginSuccessResponse",
                fields={
                    "access": drf_serializers.CharField(),
                    "refresh": drf_serializers.CharField(),
                    "user_id": drf_serializers.IntegerField(),
                    "role": drf_serializers.CharField(),
                    "tenant_id": drf_serializers.IntegerField(allow_null=True),
                    "stores": drf_serializers.ListField(),
                    "current_store": drf_serializers.JSONField(allow_null=True),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class LoginView(generics.GenericAPIView):

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        if not user.is_active:
            return Response({"detail": "Email not verified. Please activate your account."}, 
                          status=status.HTTP_403_FORBIDDEN)

        token_data = login_user(user)
        return Response(token_data)


@extend_schema_view(
    get=extend_schema(
        summary="Activate account by token",
        description="Activate account using the one-time activation token, then return JWT tokens.",
        tags=["Auth"],
        examples=[
            OpenApiExample(
                name="Activation Success",
                value={
                    "detail": "Account activated successfully!",
                    "access": "<jwt-access-token>",
                    "refresh": "<jwt-refresh-token>",
                    "user_id": 12,
                    "role": "Store Owner",
                    "tenant_id": 12,
                    "stores": [
                        {
                            "id": 1,
                            "name": "My Store",
                            "slug": "my-store",
                            "subdomain": "my-store",
                        }
                    ],
                    "current_store": {
                        "id": 1,
                        "name": "My Store",
                        "slug": "my-store",
                        "subdomain": "my-store",
                    },
                },
                response_only=True,
            ),
        ],
        responses={
            200: inline_serializer(
                name="ActivateSuccessResponse",
                fields={
                    "detail": drf_serializers.CharField(),
                    "access": drf_serializers.CharField(),
                    "refresh": drf_serializers.CharField(),
                    "user_id": drf_serializers.IntegerField(),
                    "role": drf_serializers.CharField(),
                    "tenant_id": drf_serializers.IntegerField(allow_null=True),
                    "stores": drf_serializers.ListField(),
                    "current_store": drf_serializers.JSONField(allow_null=True),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class ActivateView(generics.GenericAPIView):
    """Activate user account using UUID token."""
    
    permission_classes = [AllowAny]

    def get(self, request, token):
        """
        GET /api/auth/activate/<uuid:token>/
        """
        try:
            user = activate_user_by_token(token)
            token_data = login_user(user)
            return Response(
                {
                    "detail": "Account activated successfully!",
                    **token_data,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MeView(generics.GenericAPIView):
    """
    Return identity for the currently authenticated user.
    GET /api/auth/me/
    """

    serializer_class = CurrentUserSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get current authenticated user",
        description="Return identity data for the currently authenticated user session.",
        tags=["Auth"],
        responses={
            200: CurrentUserSerializer,
            **DOC_ERROR_RESPONSES,
        },
    )
    def get(self, request):
        serializer = self.get_serializer(request.user)
        payload = dict(serializer.data)
        payload.update(get_auth_bootstrap_store_payload(request.user))
        return Response(payload, status=status.HTTP_200_OK)
