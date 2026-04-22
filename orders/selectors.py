from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Max,
    QuerySet,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from products.models import Product

from .models import Customer, Order, OrderItem


def get_owner_orders_for_store(store_id: int, tenant_id: int) -> QuerySet:
    """
    Return owner orders for a single store scoped by tenant and store.
    """
    return (
        Order.objects.filter(
            store_id=store_id,
            tenant_id=tenant_id,
        )
        .select_related("customer", "store")
        .prefetch_related("items", "items__product", "customer__addresses")
        .order_by("-created_at")
    )


def get_owner_customers_for_store(store_id: int, tenant_id: int) -> QuerySet:
    """
    Return owner customers for a single store with aggregated order metrics.
    """
    return (
        Customer.objects.filter(
            store_id=store_id,
            tenant_id=tenant_id,
        )
        .annotate(
            total_spent=Coalesce(
                Sum("orders__total_price"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            last_order_at=Max("orders__created_at"),
            orders_count=Count("orders", distinct=True),
        )
        .order_by("-created_at")
    )


def get_dashboard_stats_for_store(store_id: int, tenant_id: int) -> dict:
    """
    Return store dashboard aggregate stats scoped by tenant and store.
    """
    order_stats = Order.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
    ).aggregate(
        total_orders=Count("id"),
        total_revenue=Coalesce(
            Sum("total_price"),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )

    product_stats = Product.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
    ).aggregate(
        total_products=Count("id"),
    )

    customer_stats = Customer.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
    ).aggregate(
        total_customers=Count("id"),
    )

    return {
        "total_orders": order_stats["total_orders"] or 0,
        "total_revenue": order_stats["total_revenue"] or Decimal("0.00"),
        "total_products": product_stats["total_products"] or 0,
        "total_customers": customer_stats["total_customers"] or 0,
    }


def get_recent_orders_for_store_dashboard(
    store_id: int,
    tenant_id: int,
    limit: int = 5,
) -> QuerySet:
    """
    Return recent dashboard orders scoped by tenant and store.
    """
    return (
        Order.objects.filter(
            store_id=store_id,
            tenant_id=tenant_id,
        )
        .select_related("customer")
        .annotate(
            customer_name=F("customer__name"),
            total=F("total_price"),
        )
        .values("id", "customer_name", "total", "status", "created_at")
        .order_by("-created_at")[:limit]
    )


def get_top_products_for_store_dashboard(
    store_id: int,
    tenant_id: int,
    limit: int = 5,
) -> list[dict]:
    """
    Return top products for dashboard based on order items.
    """
    revenue_expression = ExpressionWrapper(
        F("product_price") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    aggregated_rows = (
        OrderItem.objects.filter(
            order__store_id=store_id,
            order__tenant_id=tenant_id,
        )
        # MVP-safe fallback: when product is deleted (NULL FK), keep output shape
        # stable by returning id=0. This can move to null later if contract changes.
        .annotate(
            product_ref_id=Coalesce("product_id", Value(0), output_field=IntegerField()),
            name=Coalesce("product__name", "product_name"),
        )
        .values("product_ref_id", "name")
        .annotate(
            sales_count=Coalesce(
                Sum("quantity"),
                Value(0),
                output_field=IntegerField(),
            ),
            revenue_total=Coalesce(
                Sum(revenue_expression),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        .order_by("-sales_count", "-revenue_total", "product_ref_id")[:limit]
    )

    return [
        {
            "id": row["product_ref_id"],
            "name": row["name"],
            "sales_count": row["sales_count"],
            "revenue_total": row["revenue_total"],
        }
        for row in aggregated_rows
    ]
