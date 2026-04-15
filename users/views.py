from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .serializers import RegisterSerializer, LoginSerializer, CurrentUserSerializer
from .services import (
    register_user,
    login_user,
    send_activation_email,
    activate_user_by_token,
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
            return Response({
                "detail": "Account activated successfully!",
                "access": token_data['access'],
                "refresh": token_data['refresh'],
                "user_id": user.id,
                "role": user.role,
                "tenant_id": user.tenant_id,
            }, status=status.HTTP_200_OK)
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
        description="Protected endpoint that returns identity data for the currently authenticated user.",
        responses={200: CurrentUserSerializer},
    )
    def get(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
