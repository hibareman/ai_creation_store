from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .serializers import RegisterSerializer, LoginSerializer
from .services import register_user, login_user


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

        token_data = login_user(user)

        return Response(token_data, status=status.HTTP_201_CREATED)


class LoginView(generics.GenericAPIView):

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        token_data = login_user(user)

        return Response(token_data)