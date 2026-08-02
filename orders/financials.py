"""Centralized commission calculations for order reports and dashboards."""

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from .models import Order


MONEY_QUANTUM = Decimal("0.01")


def quantize_money(value) -> Decimal:
    """Normalize a money value to two decimal places."""
    return Decimal(str(value or 0)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def get_platform_commission_rate() -> Decimal:
    """Return the configured decimal commission rate and validate its range."""
    rate = Decimal(str(getattr(settings, "PLATFORM_COMMISSION_RATE", Decimal("0.10"))))
    if rate < Decimal("0") or rate > Decimal("1"):
        raise ValueError("PLATFORM_COMMISSION_RATE must be between 0 and 1")
    return rate


def get_store_currency(store) -> str:
    """Resolve the store currency with a safe USD fallback."""
    try:
        store_settings = store.settings
    except (ObjectDoesNotExist, AttributeError):
        return "USD"

    currency = (getattr(store_settings, "currency", "USD") or "USD").strip().upper()
    return currency or "USD"


def build_delivered_orders_financial_summary(
    *,
    total_sales,
    delivered_orders_count: int,
    store,
) -> dict:
    """Build an aggregate financial report from delivered-order sales only."""
    commission_rate = get_platform_commission_rate()
    recognized_sales = quantize_money(total_sales)
    platform_commission = quantize_money(recognized_sales * commission_rate)
    store_net_profit = quantize_money(recognized_sales - platform_commission)

    return {
        "completed_orders_count": int(delivered_orders_count or 0),
        "total_sales": recognized_sales,
        "commission_rate_percent": quantize_money(commission_rate * Decimal("100")),
        "platform_commission": platform_commission,
        "store_net_profit": store_net_profit,
        "currency": get_store_currency(store),
    }


def build_order_financial_summary(order) -> dict:
    """
    Build a single-order financial breakdown.

    Commission, recognized sales, and store profit are applied only when the
    order status is ``delivered``. Other statuses return zero recognized
    financial values while preserving the original order total.
    """
    order_total = quantize_money(getattr(order, "total_price", 0))
    commission_applied = getattr(order, "status", None) == Order.STATUS_DELIVERED
    recognized_sales = order_total if commission_applied else Decimal("0.00")

    aggregate = build_delivered_orders_financial_summary(
        total_sales=recognized_sales,
        delivered_orders_count=1 if commission_applied else 0,
        store=order.store,
    )

    return {
        "order_total": order_total,
        "commission_applied": commission_applied,
        "recognized_sales": aggregate["total_sales"],
        "commission_rate_percent": aggregate["commission_rate_percent"],
        "platform_commission": aggregate["platform_commission"],
        "store_net_profit": aggregate["store_net_profit"],
        "currency": aggregate["currency"],
    }
