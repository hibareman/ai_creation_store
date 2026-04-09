from rest_framework import serializers
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
    - role: User role - Admin, Store Owner, or Customer (required)
    
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
                "help_text": "User role: Admin, Store Owner, or Customer",
                "required": True,
            },
        }

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
            raise serializers.ValidationError("Invalid credentials")

        if not user.check_password(data["password"]):
            raise serializers.ValidationError("Invalid credentials")

        data["user"] = user
        return data