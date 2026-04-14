from django.db import models

from stores.models import Store


class ThemeTemplate(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class StoreThemeConfig(models.Model):
    store = models.OneToOneField(
        Store,
        on_delete=models.CASCADE,
        related_name="theme_config",
    )
    theme_template = models.ForeignKey(
        ThemeTemplate,
        on_delete=models.PROTECT,
        related_name="store_theme_configs",
    )
    primary_color = models.CharField(max_length=20)
    secondary_color = models.CharField(max_length=20)
    font_family = models.CharField(max_length=100)
    logo_url = models.URLField(blank=True, default="")
    banner_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Theme config for {self.store.name}"
