from django.db import models


class PlatformAdminSettings(models.Model):
    support_email = models.EmailField(default="support@example.com")
    default_currency = models.CharField(max_length=3, default="USD")
    allow_public_registration = models.BooleanField(default=True)
    require_store_approval = models.BooleanField(default=True)
    maintenance_mode = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform admin settings"
        verbose_name_plural = "Platform admin settings"

    def __str__(self):
        return "Platform admin settings"


def get_platform_admin_settings():
    settings_obj, _created = PlatformAdminSettings.objects.get_or_create(pk=1)
    return settings_obj
