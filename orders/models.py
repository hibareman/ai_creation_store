from django.db import models

from products.models import Product
from stores.models import Store


class Customer(models.Model):
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="customers",
    )
    tenant_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Tenant ID for multi-tenant isolation",
    )
    email = models.EmailField()
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True, default="")
    avatar_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.tenant_id is None and self.store_id:
            store_tenant_id = getattr(self.store, "tenant_id", None)
            if store_tenant_id is not None:
                self.tenant_id = store_tenant_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.email})"


class Address(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="addresses",
    )
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    street = models.CharField(max_length=255)
    postal_code = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.country}, {self.city}, {self.street}"


class Order(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="orders",
        null=True,
        blank=True,
    )
    tenant_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Tenant ID for multi-tenant isolation",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.tenant_id is None:
            if self.store_id:
                store_tenant_id = getattr(self.store, "tenant_id", None)
                if store_tenant_id is not None:
                    self.tenant_id = store_tenant_id
            elif self.customer_id:
                customer_tenant_id = getattr(self.customer, "tenant_id", None)
                if customer_tenant_id is not None:
                    self.tenant_id = customer_tenant_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order #{self.id} - Customer #{self.customer_id}"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=255)
    product_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product_name} x{self.quantity} (Order #{self.order_id})"