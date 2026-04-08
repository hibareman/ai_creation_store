from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid


class User(AbstractUser):

    ROLE_CHOICES = (
        ("Super Admin", "Super Admin"),
        ("Store Owner", "Store Owner"),
    )

    email = models.EmailField(unique=True)

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="Store Owner"
    )

    tenant_id = models.IntegerField(null=True, blank=True)
    
    # حقل توكن التفعيل - UUID بسيط وفريد
    activation_token = models.UUIDField(default=uuid.uuid4, unique=True, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return f"{self.email} ({self.role})"