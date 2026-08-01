from datetime import timedelta
from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Max,
    Q,
    QuerySet,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from categories.models import Category
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
        .select_related("customer", "store", "store__settings")
        .prefetch_related("items", "items__product", "customer__addresses")
        .order_by("-created_at")
    )


def filter_owner_orders_by_status(queryset: QuerySet, status: str) -> QuerySet:
    """
    Apply status filtering to an already store/tenant-scoped orders queryset.
    """
    return queryset.filter(status=status)


def search_owner_orders(queryset: QuerySet, search: str) -> QuerySet:
    """Search scoped orders by order ID, customer name, or customer email."""
    criteria = Q(customer__name__icontains=search) | Q(customer__email__icontains=search)

    normalized = search.strip()
    order_id_text = normalized[4:] if normalized.upper().startswith("ORD-") else normalized
    if order_id_text.isdigit():
        criteria |= Q(id=int(order_id_text))

    return queryset.filter(criteria)


def order_owner_orders(queryset: QuerySet, ordering: str) -> QuerySet:
    """Apply a validated ordering expression to a scoped orders queryset."""
    return queryset.order_by(ordering)


def get_owner_orders_financial_totals(queryset: QuerySet) -> dict:
    """Aggregate delivered-order totals from an already scoped report queryset."""
    delivered_filter = Q(status=Order.STATUS_DELIVERED)
    values = queryset.aggregate(
        delivered_orders_count=Count("id", filter=delivered_filter),
        total_sales=Coalesce(
            Sum("total_price", filter=delivered_filter),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )
    return {
        "delivered_orders_count": values["delivered_orders_count"] or 0,
        "total_sales": values["total_sales"] or Decimal("0.00"),
    }


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
    Return smart dashboard aggregates scoped by tenant and store.

    Sales are recognized only from delivered orders. This keeps financial
    metrics aligned with the completed-sales business rule.
    """
    delivered_filter = Q(status=Order.STATUS_DELIVERED)
    pending_filter = Q(status=Order.STATUS_PENDING)

    order_stats = Order.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
    ).aggregate(
        total_orders=Count("id"),
        delivered_orders=Count("id", filter=delivered_filter),
        pending_orders=Count("id", filter=pending_filter),
        total_sales=Coalesce(
            Sum("total_price", filter=delivered_filter),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )

    product_stats = Product.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
    ).aggregate(total_products=Count("id"))

    category_stats = Category.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
    ).aggregate(total_categories=Count("id"))

    customer_stats = Customer.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
    ).aggregate(total_customers=Count("id"))

    total_sales = order_stats["total_sales"] or Decimal("0.00")
    return {
        "total_orders": order_stats["total_orders"] or 0,
        "delivered_orders": order_stats["delivered_orders"] or 0,
        "pending_orders": order_stats["pending_orders"] or 0,
        # Backward-compatible alias retained for the existing dashboard UI.
        "total_revenue": total_sales,
        "total_sales": total_sales,
        "total_products": product_stats["total_products"] or 0,
        "total_categories": category_stats["total_categories"] or 0,
        "total_customers": customer_stats["total_customers"] or 0,
    }



def count_stale_pending_orders_for_store(
    store_id: int,
    tenant_id: int,
    stale_after_days: int,
) -> int:
    """Count pending orders older than the configured review threshold."""
    cutoff = timezone.now() - timedelta(days=max(stale_after_days, 0))
    return Order.objects.filter(
        store_id=store_id,
        tenant_id=tenant_id,
        status=Order.STATUS_PENDING,
        created_at__lt=cutoff,
    ).count()

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
            order__status=Order.STATUS_DELIVERED,
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
