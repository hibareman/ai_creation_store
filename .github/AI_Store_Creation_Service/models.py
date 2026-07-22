from django.db import models


class AIStoreAuditLog(models.Model):
    """
    Lightweight audit trail for core AI workflow events.

    This model intentionally stores only compact operational context and
    short messages to avoid payload bloat and sensitive data leakage.
    """

    tenant_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    store_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    actor_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    action = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=16, db_index=True)
    message = models.CharField(max_length=500, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return (
            f"AIStoreAuditLog(action={self.action}, status={self.status}, "
            f"tenant_id={self.tenant_id}, store_id={self.store_id})"
        )
