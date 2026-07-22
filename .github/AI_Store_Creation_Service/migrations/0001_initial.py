from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AIStoreAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("store_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("actor_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("status", models.CharField(db_index=True, max_length=16)),
                ("message", models.CharField(blank=True, default="", max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
