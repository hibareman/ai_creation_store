from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from products.models import Product
from products.selectors import get_public_product_detail, get_public_products_for_store

from .models import Address, Customer, Order, OrderItem
from .financials import (
    build_delivered_orders_financial_summary,
)
from .selectors import (
    count_stale_pending_orders_for_store,
    filter_owner_orders_by_status,
    order_owner_orders,
    search_owner_orders,
    get_dashboard_stats_for_store,
    get_owner_customers_for_store,
    get_owner_orders_for_store,
    get_owner_orders_financial_totals,
    get_recent_orders_for_store_dashboard,
    get_top_products_for_store_dashboard,
)


ALLOWED_ORDER_STATUSES = {
    "pending",
    "processing",
    "shipped",
    "delivered",
    "cancelled",
}

OWNER_ORDER_LIST_ALLOWED_STATUSES = ALLOWED_ORDER_STATUSES

OWNER_ORDER_ALLOWED_ORDERING = {
    "created_at",
    "-created_at",
    "total_price",
    "-total_price",
}

CART_CACHE_TTL = getattr(settings, "CART_CACHE_TTL", 60 * 60 * 24)


def _validate_public_store_context(store) -> None:
    if store is None or getattr(store, "id", None) is None or getattr(store, "tenant_id", None) is None:
        raise ValidationError("Store is not available for cart")


def create_customer_order(
    store,
    customer_data: dict,
    address_data: dict,
    items_data: list[dict],
):
    """
    Create a customer-facing order for a public store flow.

    Creates or reuses Customer, creates Address, creates Order and OrderItems,
    and returns a minimal payload for response serialization.
    """
    store_id = getattr(store, "id", None)
    tenant_id = getattr(store, "tenant_id", None)
    if store is None or store_id is None or tenant_id is None:
        raise ValidationError("Store is not available for ordering")

    if not items_data:
        raise ValidationError("Order items are required")

    normalized_items = []
    requested_product_ids = []
    for item in items_data:
        product_id = item.get("product_id")
        quantity = item.get("quantity")

        if product_id is None or quantity is None:
            raise ValidationError("Invalid order items")

        try:
            product_id = int(product_id)
            quantity = int(quantity)
        except (TypeError, ValueError):
            raise ValidationError("Invalid order items")

        if quantity < 1:
            raise ValidationError("Invalid order items")

        normalized_items.append(
            {
                "product_id": product_id,
                "quantity": quantity,
            }
        )
        requested_product_ids.append(product_id)

    unique_product_ids = set(requested_product_ids)
    products = Product.objects.filter(
        id__in=unique_product_ids,
        store_id=store_id,
        tenant_id=tenant_id,
        status="active",
    )
    products_by_id = {product.id: product for product in products}
    if len(products_by_id) != len(unique_product_ids):
        raise ValidationError("One or more products are unavailable")

    customer_email = (customer_data.get("email") or "").strip().lower()
    customer_name = (customer_data.get("name") or "").strip()
    customer_phone = (customer_data.get("phone") or "").strip()
    if not customer_email or not customer_name:
        raise ValidationError("Invalid customer data")

    country = (address_data.get("country") or "").strip()
    city = (address_data.get("city") or "").strip()
    street = (address_data.get("street") or "").strip()
    postal_code = (address_data.get("postal_code") or "").strip()
    if not country or not city or not street or not postal_code:
        raise ValidationError("Invalid address data")

    with transaction.atomic():
        customer = Customer.objects.filter(
            store_id=store_id,
            tenant_id=tenant_id,
            email__iexact=customer_email,
        ).first()

        if customer is None:
            customer = Customer.objects.create(
                store=store,
                tenant_id=tenant_id,
                name=customer_name,
                email=customer_email,
                phone=customer_phone,
            )
        else:
            update_fields = []
            if customer_name and customer.name != customer_name:
                customer.name = customer_name
                update_fields.append("name")
            if customer.phone != customer_phone:
                customer.phone = customer_phone
                update_fields.append("phone")
            if update_fields:
                customer.save(update_fields=update_fields)

        Address.objects.create(
            customer=customer,
            country=country,
            city=city,
            street=street,
            postal_code=postal_code,
        )

        order = Order.objects.create(
            store=store,
            customer=customer,
            tenant_id=tenant_id,
            status=Order.STATUS_PENDING,
            total_price=Decimal("0.00"),
        )

        total_price = Decimal("0.00")
        order_items = []
        for item in normalized_items:
            product = products_by_id[item["product_id"]]
            quantity = item["quantity"]
            total_price += product.price * quantity
            order_items.append(
                OrderItem(
                    order=order,
                    product=product,
                    product_name=product.name,
                    product_price=product.price,
                    quantity=quantity,
                )
            )

        OrderItem.objects.bulk_create(order_items)

        order.total_price = total_price
        order.save(update_fields=["total_price"])

    return {
        "order_id": order.id,
        "status": order.status,
        "total": order.total_price,
    }


def _normalize_cart_token(cart_token: str | None) -> str:
    token = (cart_token or "").strip()
    return token or uuid4().hex


def _build_cart_cache_key(store, cart_token: str) -> str:
    return f"public_cart:store:{store.id}:tenant:{store.tenant_id}:token:{cart_token}"


def _load_cart_items(store, cart_token: str) -> dict[int, int]:
    cache_key = _build_cart_cache_key(store, cart_token)
    cached_value = cache.get(cache_key) or {}
    raw_items = cached_value.get("items", {})
    if not isinstance(raw_items, dict):
        return {}

    normalized_items = {}
    for product_id_raw, quantity_raw in raw_items.items():
        try:
            product_id = int(product_id_raw)
            quantity = int(quantity_raw)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and quantity >= 1:
            normalized_items[product_id] = quantity
    return normalized_items


def _save_cart_items(store, cart_token: str, items: dict[int, int]) -> None:
    cache_key = _build_cart_cache_key(store, cart_token)
    serialized_items = {str(product_id): quantity for product_id, quantity in items.items()}
    cache.set(cache_key, {"items": serialized_items}, timeout=CART_CACHE_TTL)


def _delete_cart(store, cart_token: str) -> None:
    cache_key = _build_cart_cache_key(store, cart_token)
    cache.delete(cache_key)


def _build_public_cart_payload(store, cart_token: str, items: dict[int, int]) -> dict:
    if not items:
        return {
            "cart_token": cart_token,
            "store_id": store.id,
            "items": [],
            "total": Decimal("0.00"),
        }

    product_ids = list(items.keys())
    products = get_public_products_for_store(store).filter(id__in=product_ids)
    products_by_id = {product.id: product for product in products}

    response_items = []
    total = Decimal("0.00")
    stale_items_removed = False

    for product_id, quantity in items.items():
        product = products_by_id.get(product_id)
        if product is None:
            stale_items_removed = True
            continue

        line_total = product.price * quantity
        total += line_total
        response_items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "price": product.price,
                "quantity": quantity,
                "line_total": line_total,
            }
        )

    if stale_items_removed:
        sanitized_items = {item["product_id"]: item["quantity"] for item in response_items}
        if sanitized_items:
            _save_cart_items(store, cart_token, sanitized_items)
        else:
            _delete_cart(store, cart_token)

    return {
        "cart_token": cart_token,
        "store_id": store.id,
        "items": response_items,
        "total": total,
    }


def get_public_cart_payload(store, cart_token: str | None = None) -> dict:
    """
    Return the public cart payload for a store-scoped cart token.
    """
    _validate_public_store_context(store)

    resolved_cart_token = _normalize_cart_token(cart_token)
    items = _load_cart_items(store, resolved_cart_token)
    return _build_public_cart_payload(store, resolved_cart_token, items)


def add_item_to_public_cart(
    store,
    product_id: int,
    quantity: int,
    cart_token: str | None = None,
) -> dict:
    """
    Add an item to the public cart and merge quantity if product already exists.
    """
    _validate_public_store_context(store)

    if quantity < 1:
        raise ValidationError("Quantity must be at least 1")

    product = get_public_product_detail(store, product_id)
    if not product:
        raise ValidationError("Product is unavailable")

    resolved_cart_token = _normalize_cart_token(cart_token)
    items = _load_cart_items(store, resolved_cart_token)
    items[product.id] = items.get(product.id, 0) + quantity
    _save_cart_items(store, resolved_cart_token, items)
    return _build_public_cart_payload(store, resolved_cart_token, items)


def update_public_cart_item_quantity(
    store,
    product_id: int,
    quantity: int,
    cart_token: str | None = None,
) -> dict:
    """
    Replace quantity for a product in the public cart.
    """
    _validate_public_store_context(store)

    if quantity < 1:
        raise ValidationError("Quantity must be at least 1")

    product = get_public_product_detail(store, product_id)
    if not product:
        raise ValidationError("Product is unavailable")

    resolved_cart_token = _normalize_cart_token(cart_token)
    items = _load_cart_items(store, resolved_cart_token)
    items[product.id] = quantity
    _save_cart_items(store, resolved_cart_token, items)
    return _build_public_cart_payload(store, resolved_cart_token, items)


def remove_item_from_public_cart(
    store,
    product_id: int,
    cart_token: str | None = None,
) -> dict:
    """
    Remove an item from the public cart.
    """
    _validate_public_store_context(store)

    resolved_cart_token = _normalize_cart_token(cart_token)
    items = _load_cart_items(store, resolved_cart_token)
    items.pop(int(product_id), None)

    if items:
        _save_cart_items(store, resolved_cart_token, items)
    else:
        _delete_cart(store, resolved_cart_token)

    return _build_public_cart_payload(store, resolved_cart_token, items)


def clear_public_cart(store, cart_token: str | None = None) -> dict:
    """
    Clear all items from the public cart.
    """
    _validate_public_store_context(store)

    resolved_cart_token = _normalize_cart_token(cart_token)
    _delete_cart(store, resolved_cart_token)
    return {
        "cart_token": resolved_cart_token,
        "store_id": store.id,
        "items": [],
        "total": Decimal("0.00"),
    }


def checkout_cart_to_order(
    store,
    cart_token: str | None,
    customer_data: dict,
    address_data: dict,
):
    """
    Convert a store-scoped public cart into an order and clear the cart on success.
    """
    _validate_public_store_context(store)
    resolved_cart_token = _normalize_cart_token(cart_token)
    cart_items = _load_cart_items(store, resolved_cart_token)
    if not cart_items:
        raise ValidationError("Cart is empty")

    items_data = [
        {"product_id": product_id, "quantity": quantity}
        for product_id, quantity in cart_items.items()
    ]

    with transaction.atomic():
        payload = create_customer_order(
            store=store,
            customer_data=customer_data,
            address_data=address_data,
            items_data=items_data,
        )

    _delete_cart(store, resolved_cart_token)
    return payload


def validate_owner_store_access(store, user):
    """
    Validate that the authenticated user can access and manage the store.
    """
    if getattr(user, "tenant_id", None) != store.tenant_id:
        raise PermissionDenied("You do not have access to this store")

    if getattr(user, "id", None) != store.owner_id:
        raise PermissionDenied("You do not own this store")


def get_owner_orders_payload(
    store,
    user=None,
    status=None,
    search=None,
    ordering=None,
):
    """Build the owner orders payload with scoped search, filtering, and ordering."""
    if user is not None:
        validate_owner_store_access(store, user)

    items = get_owner_orders_for_store(
        store_id=store.id,
        tenant_id=store.tenant_id,
    )

    normalized_search = (search or "").strip()
    if normalized_search:
        items = search_owner_orders(items, normalized_search)

    normalized_status = (status or "").strip()
    if normalized_status:
        if normalized_status not in OWNER_ORDER_LIST_ALLOWED_STATUSES:
            raise ValidationError({"status": "Unsupported order status"})
        items = filter_owner_orders_by_status(items, normalized_status)

    normalized_ordering = (ordering or "").strip()
    if normalized_ordering:
        if normalized_ordering not in OWNER_ORDER_ALLOWED_ORDERING:
            raise ValidationError({"ordering": "Unsupported ordering value"})
        items = order_owner_orders(items, normalized_ordering)

    financial_totals = get_owner_orders_financial_totals(items)

    return {
        "store_id": store.id,
        "financial_summary": build_delivered_orders_financial_summary(
            total_sales=financial_totals["total_sales"],
            delivered_orders_count=financial_totals["delivered_orders_count"],
            store=store,
        ),
        "items": items,
    }


def get_owner_order_detail(store, order_id: int, user=None):
    """
    Resolve one owner order detail for a store.
    """
    if user is not None:
        validate_owner_store_access(store, user)

    return get_order_by_id_for_owner(
        store_id=store.id,
        tenant_id=store.tenant_id,
        order_id=order_id,
    )


def get_owner_customers_payload(store, user=None):
    """
    Build owner customers payload for a store.
    """
    if user is not None:
        validate_owner_store_access(store, user)

    items = get_owner_customers_for_store(
        store_id=store.id,
        tenant_id=store.tenant_id,
    )
    return {
        "store_id": store.id,
        "items": items,
    }


def _build_dashboard_financial_summary(store, stats: dict) -> dict:
    return build_delivered_orders_financial_summary(
        total_sales=stats["total_sales"],
        delivered_orders_count=stats["delivered_orders"],
        store=store,
    )

def _build_store_readiness(store, stats: dict) -> dict:
    checks = {
        "has_products": stats["total_products"] > 0,
        "has_categories": stats["total_categories"] > 0,
        "has_subdomain": bool((getattr(store, "subdomain", None) or "").strip()),
        "is_published": bool(getattr(store, "is_published", False) and store.status == "active"),
    }

    is_ready_for_publish = all(
        checks[key]
        for key in ("has_products", "has_categories", "has_subdomain")
    )

    if is_ready_for_publish and checks["is_published"]:
        readiness_status = "published"
    elif is_ready_for_publish:
        readiness_status = "ready_to_publish"
    else:
        readiness_status = "incomplete"

    missing_requirements = []
    if not checks["has_categories"]:
        missing_requirements.append("categories")
    if not checks["has_products"]:
        missing_requirements.append("products")
    if not checks["has_subdomain"]:
        missing_requirements.append("subdomain")
    if not checks["is_published"]:
        missing_requirements.append("publishing")

    completed_checks = sum(1 for value in checks.values() if value)
    return {
        "status": readiness_status,
        "is_ready_for_publish": is_ready_for_publish,
        "completion_percentage": completed_checks * 25,
        "checks": checks,
        "missing_requirements": missing_requirements,
    }


def _build_dashboard_recommended_actions(readiness: dict, stats: dict) -> list[dict]:
    checks = readiness["checks"]
    actions = []
    low_product_threshold = max(
        int(getattr(settings, "SMART_DASHBOARD_LOW_PRODUCT_THRESHOLD", 5)),
        1,
    )

    if not checks["has_categories"]:
        actions.append({
            "code": "add_category",
            "title": "Organize your catalog",
            "message": "Your store has no categories yet. Add categories to organize products and make browsing easier for customers.",
            "target": "categories",
            "priority": "high",
        })

    if not checks["has_products"]:
        actions.append({
            "code": "add_product",
            "title": "Add your first products",
            "message": "Your store has no products yet. Add products so the store can be reviewed and prepared for publishing.",
            "target": "products",
            "priority": "high",
        })
    elif stats["total_products"] < low_product_threshold:
        actions.append({
            "code": "add_more_products",
            "title": "Expand your product catalog",
            "message": f"Your store currently has only {stats['total_products']} product(s). Add more products to offer customers better variety.",
            "target": "products",
            "priority": "medium",
        })

    if not checks["has_subdomain"]:
        actions.append({
            "code": "set_subdomain",
            "title": "Set your store link",
            "message": "Your store does not have a public link yet. Choose a unique subdomain so customers can access it.",
            "target": "store_settings",
            "priority": "medium",
        })

    if readiness["is_ready_for_publish"] and not checks["is_published"]:
        actions.append({
            "code": "publish_store",
            "title": "Publish your store",
            "message": "Your store is ready. Publish it now to make it available to customers.",
            "target": "publish",
            "priority": "high",
        })

    if checks["is_published"] and stats["delivered_orders"] == 0:
        actions.append({
            "code": "improve_sales",
            "title": "Work toward your first completed sale",
            "message": "No completed sales have been recorded yet. Review your product selection and store presentation to attract customers.",
            "target": "products",
            "priority": "medium",
        })

    return actions[:4]


def _build_dashboard_alerts(store, stats: dict) -> list[dict]:
    alerts = []
    pending_orders = stats["pending_orders"]

    if pending_orders > 0:
        alerts.append({
            "code": "orders_need_review",
            "title": "New orders need review",
            "message": f"You have {pending_orders} pending order(s) that need review and processing.",
            "severity": "info",
            "target": "orders",
            "count": pending_orders,
        })

    stale_after_days = max(
        int(getattr(settings, "SMART_DASHBOARD_STALE_PENDING_ORDER_DAYS", 3)),
        1,
    )
    stale_pending_orders = count_stale_pending_orders_for_store(
        store_id=store.id,
        tenant_id=store.tenant_id,
        stale_after_days=stale_after_days,
    )
    if stale_pending_orders > 0:
        alerts.append({
            "code": "stale_pending_orders",
            "title": "Some orders have been waiting too long",
            "message": f"You have {stale_pending_orders} order(s) pending for more than {stale_after_days} days. Review them to avoid delays.",
            "severity": "warning",
            "target": "orders",
            "count": stale_pending_orders,
        })

    return alerts


def _build_dashboard_notices(
    readiness: dict,
    recommended_actions: list[dict],
    alerts: list[dict],
) -> list[dict]:
    if (
        readiness["status"] == "published"
        and not recommended_actions
        and not alerts
    ):
        return [{
            "code": "store_running_well",
            "title": "Your store is running well",
            "message": "Your store is complete and published successfully. No actions are required at this time.",
            "type": "success",
        }]

    return []


def get_store_dashboard_payload(store, user=None):
    """
    Build the tenant-safe smart dashboard payload for a store.
    """
    if user is not None:
        validate_owner_store_access(store, user)

    stats = get_dashboard_stats_for_store(
        store_id=store.id,
        tenant_id=store.tenant_id,
    )
    readiness = _build_store_readiness(store, stats)
    recommended_actions = _build_dashboard_recommended_actions(readiness, stats)
    alerts = _build_dashboard_alerts(store, stats)

    return {
        "store_id": store.id,
        "stats": stats,
        "financial_summary": _build_dashboard_financial_summary(store, stats),
        "readiness": readiness,
        "recommended_actions": recommended_actions,
        "alerts": alerts,
        "notices": _build_dashboard_notices(readiness, recommended_actions, alerts),
        "recent_orders": get_recent_orders_for_store_dashboard(
            store_id=store.id,
            tenant_id=store.tenant_id,
        ),
        "top_products": get_top_products_for_store_dashboard(
            store_id=store.id,
            tenant_id=store.tenant_id,
        ),
    }


def get_order_by_id_for_owner(store_id: int, tenant_id: int, order_id: int):
    """
    Resolve one owner-scoped order by id with strict store/tenant scoping.
    """
    return (
        Order.objects.filter(
            id=order_id,
            store_id=store_id,
            tenant_id=tenant_id,
        )
        .select_related("customer", "store")
        .prefetch_related(
            "items",
            "items__product",
            "items__product__images",
            "customer__addresses",
        )
        .first()
    )


def update_order_status(store, order, status, user=None):
    """
    Update order status for an owner-scoped order.
    """
    if user is not None:
        validate_owner_store_access(store, user)

    if order.store_id != store.id or order.tenant_id != store.tenant_id:
        raise PermissionDenied("You do not have access to this order")

    if status not in ALLOWED_ORDER_STATUSES:
        raise ValidationError("Invalid order status")

    if order.status != status:
        order.status = status
        order.save(update_fields=["status"])

    return order
