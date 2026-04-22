from django.db import models
from django.conf import settings
from django.utils.text import slugify

class Store(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("setup", "Setup"),
        ("active", "Active"),
        ("inactive", "Inactive"),
    )

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stores')
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    subdomain = models.SlugField(unique=True, null=True, blank=True, db_index=True)
    description = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="setup")
    is_published = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    tenant_id = models.IntegerField(null=True, blank=True, db_index=True)  # Added db_index for performance
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['tenant_id']),
            models.Index(fields=['tenant_id', 'slug']),
        ]

    def save(self, *args, **kwargs):
        # Normalize optional public subdomain at model layer.
        if self.subdomain is not None:
            normalized_subdomain = self.subdomain.strip().lower()
            self.subdomain = slugify(normalized_subdomain) if normalized_subdomain else None

        if not self.slug:
            base_slug = slugify(self.name)
        else:
            base_slug = self.slug

        self.slug = base_slug
        counter = 1
        # NOTE:
        # This loop ensures slug uniqueness at the model level.
        # In high-scale systems, consider replacing with database constraints + retry logic.
        while Store.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
            self.slug = f"{base_slug}-{counter}"
            counter += 1

        # Ensure tenant_id is never None (critical for multi-tenant)
        if not self.tenant_id:
            if self.owner_id:
                owner_tenant_id = getattr(self.owner, 'tenant_id', None)
                if owner_tenant_id is not None:
                    self.tenant_id = owner_tenant_id

            super().save(*args, **kwargs)

            # If tenant_id is still None, set it to the store's own id
            if not self.tenant_id:
                self.tenant_id = self.id
                super().save(update_fields=['tenant_id'])
        else:
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.owner})"


class StoreSettings(models.Model):
    store = models.OneToOneField(Store, on_delete=models.CASCADE, related_name='settings')
    store_email = models.EmailField(blank=True, default='')
    store_phone = models.CharField(max_length=30, blank=True, default='')
    currency = models.CharField(max_length=3, default='USD')
    language = models.CharField(max_length=10, default='en')
    timezone = models.CharField(max_length=50, default='UTC')
    email_notifications = models.BooleanField(default=True)
    order_notifications = models.BooleanField(default=True)
    marketing_notifications = models.BooleanField(default=False)
    two_factor_auth = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settings for {self.store.name}"


class StoreDomain(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='domains')
    domain = models.CharField(max_length=255, unique=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.domain} ({self.store.name})"
