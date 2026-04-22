from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from products.models import Product
from products.selectors import get_public_product_detail, get_public_products_for_store

from .models import Address, Customer, Order, OrderItem
from .selectors import (
    get_dashboard_stats_for_store,
    get_owner_customers_for_store,
    get_owner_orders_for_store,
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


def get_owner_orders_payload(store, user=None):
    """
    Build owner orders payload for a store.
    """
    if user is not None:
        validate_owner_store_access(store, user)

    items = get_owner_orders_for_store(
        store_id=store.id,
        tenant_id=store.tenant_id,
    )
    return {
        "store_id": store.id,
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


def get_store_dashboard_payload(store, user=None):
    """
    Build owner dashboard payload for a store.
    """
    if user is not None:
        validate_owner_store_access(store, user)

    return {
        "store_id": store.id,
        "stats": get_dashboard_stats_for_store(
            store_id=store.id,
            tenant_id=store.tenant_id,
        ),
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
        .prefetch_related("items", "items__product", "customer__addresses")
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
