# Generated manually for platform_admin settings persistence.

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PlatformAdminSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("support_email", models.EmailField(default="support@example.com", max_length=254)),
                ("default_currency", models.CharField(default="USD", max_length=3)),
                ("allow_public_registration", models.BooleanField(default=True)),
                ("require_store_approval", models.BooleanField(default=True)),
                ("maintenance_mode", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Platform admin settings",
                "verbose_name_plural": "Platform admin settings",
            },
        ),
    ]
