from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .serializers import RegisterSerializer, LoginSerializer
from django.core.signing import BadSignature, SignatureExpired
from .services import (
    register_user,
    login_user,
    generate_activation_token,
    send_activation_email,
    activate_user,
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
            tenant_id=request.data.get("tenant_id")
        )

        # Generate activation token and send activation email (console backend)
        token = generate_activation_token(user)
        activation_path = f"/users/activate/?token={token}"
        activation_url = request.build_absolute_uri(activation_path)
        send_activation_email(user, activation_url)

        return Response({"detail": "Activation email sent."}, status=status.HTTP_201_CREATED)


class LoginView(generics.GenericAPIView):

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        if not user.is_active:
            return Response({"detail": "Email not verified."}, status=status.HTTP_403_FORBIDDEN)

        token_data = login_user(user)

        return Response(token_data)



class ActivateView(generics.GenericAPIView):
    """Activate user account via token and return JWT tokens."""

    permission_classes = [AllowAny]

    def get(self, request):
        token = request.GET.get('token')
        if not token:
            return Response({'detail': 'Missing token.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = activate_user(token)
        except SignatureExpired:
            return Response({'detail': 'Activation token expired.'}, status=status.HTTP_400_BAD_REQUEST)
        except BadSignature:
            return Response({'detail': 'Invalid activation token.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'detail': 'Activation failed.'}, status=status.HTTP_400_BAD_REQUEST)

        # login and return tokens
        token_data = login_user(user)
        return Response(token_data)