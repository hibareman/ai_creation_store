from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from .models import User
from django.contrib.auth import get_user_model


class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration.
    
    **Purpose:** Create a new user account
    
    **Fields:**
    - username: Unique username (required, max 150 characters)
    - email: Unique email address (required)
    - password: User password (write_only, required)
    - role: User role (self-registration supports Store Owner only)
    
    **Features:**
    - Password hashing: Passwords are automatically hashed using Django's secure function
    - Email validation: Must be valid email format
    - Role assignment: Determines user permissions and access levels
    
    **Response:** Returns created user data (without password)
    """

    class Meta:
        model = User
        fields = ["username", "email", "password", "role"]

        extra_kwargs = {
            "password": {
                "write_only": True,
                "help_text": "User password (will be securely hashed)",
                "min_length": 8,
            },
            "username": {
                "help_text": "Unique username (alphanumeric, max 150 chars)",
                "max_length": 150,
            },
            "email": {
                "help_text": "Valid email address",
                "required": True,
            },
            "role": {
                "help_text": "User role (public registration supports Store Owner only)",
                "required": False,
            },
        }

    def to_internal_value(self, data):
        if "tenant_id" in data:
            raise serializers.ValidationError(
                {"tenant_id": "This field is not allowed in registration."}
            )
        return super().to_internal_value(data)

    def validate_role(self, value):
        if value != "Store Owner":
            raise serializers.ValidationError(
                "Self-registration only supports the 'Store Owner' role."
            )
        return value

    def create(self, validated_data):

        password = validated_data.pop("password")

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        return user


class LoginSerializer(serializers.Serializer):
    """
    Serializer for user login.
    
    **Purpose:** Authenticate user and return JWT tokens
    
    **Fields:**
    - email: User email address (required)
    - password: User password (required)
    
    **Features:**
    - Credential validation: Checks email and password against database
    - User lookup: By email address
    - Security: Returns error message for invalid credentials (not which field failed)
    
    **Response:** Returns user object (used to generate JWT tokens in view)
    """

    email = serializers.EmailField(
        help_text="User email address"
    )
    password = serializers.CharField(
        help_text="User password",
        write_only=True,
    )

    def validate(self, data):

        UserModel = get_user_model()

        try:
            user = UserModel.objects.get(email=data["email"])
        except UserModel.DoesNotExist:
            raise AuthenticationFailed("Invalid credentials")

        if not user.check_password(data["password"]):
            raise AuthenticationFailed("Invalid credentials")

        data["user"] = user
        return data


class CurrentUserSerializer(serializers.ModelSerializer):
    """
    Serializer for the authenticated user identity (session bootstrap).
    """

    user_id = serializers.IntegerField(source="id", read_only=True)
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "user_id",
            "username",
            "email",
            "role",
            "tenant_id",
            "is_active",
            "display_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_display_name(self, obj):
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return full_name or obj.username


class AuthStoreSummarySerializer(serializers.Serializer):
    """Store summary returned in auth/bootstrap responses."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    subdomain = serializers.CharField(allow_null=True)


class AuthBootstrapResponseSerializer(serializers.Serializer):
    """Shared auth bootstrap payload with store context."""

    stores = AuthStoreSummarySerializer(many=True)
    current_store = AuthStoreSummarySerializer(allow_null=True)


class LoginSuccessResponseSerializer(AuthBootstrapResponseSerializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user_id = serializers.IntegerField()
    role = serializers.CharField()
    tenant_id = serializers.IntegerField(allow_null=True)


class ActivateSuccessResponseSerializer(LoginSuccessResponseSerializer):
    detail = serializers.CharField()


class CurrentUserBootstrapResponseSerializer(CurrentUserSerializer):
    stores = AuthStoreSummarySerializer(many=True)
    current_store = AuthStoreSummarySerializer(allow_null=True)

    class Meta(CurrentUserSerializer.Meta):
        fields = CurrentUserSerializer.Meta.fields + [
            "stores",
            "current_store",
        ]
        read_only_fields = fields
