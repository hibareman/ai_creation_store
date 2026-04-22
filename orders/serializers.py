from rest_framework import serializers

from .models import Order, OrderItem


class OwnerOrderItemSerializer(serializers.ModelSerializer):
    """Nested order item output for owner orders responses."""

    name = serializers.CharField(source="product_name", read_only=True)
    price = serializers.DecimalField(
        source="product_price",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = OrderItem
        fields = ["id", "name", "quantity", "price"]


class OwnerOrderSerializer(serializers.ModelSerializer):
    """Single order object for owner orders list responses."""

    customer_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    total = serializers.DecimalField(
        source="total_price",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )
    items = OwnerOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "store_id",
            "customer_id",
            "customer_name",
            "email",
            "phone",
            "address",
            "total",
            "status",
            "created_at",
            "items",
        ]

    def get_customer_name(self, obj):
        if obj.customer_id and obj.customer:
            return obj.customer.name
        return None

    def get_email(self, obj):
        if obj.customer_id and obj.customer:
            return obj.customer.email
        return None

    def get_phone(self, obj):
        if obj.customer_id and obj.customer:
            phone = getattr(obj.customer, "phone", "")
            return phone or None
        return None

    def get_address(self, obj):
        if not obj.customer_id or not obj.customer:
            return None

        prefetched_cache = getattr(obj.customer, "_prefetched_objects_cache", {})
        prefetched_addresses = prefetched_cache.get("addresses")
        if prefetched_addresses is None:
            return None

        first_address = prefetched_addresses[0] if prefetched_addresses else None
        if not first_address:
            return None

        parts = [first_address.country, first_address.city, first_address.street]
        return ", ".join([part for part in parts if part])


class OwnerOrdersListResponseSerializer(serializers.Serializer):
    """Top-level owner orders list response serializer."""

    store_id = serializers.IntegerField()
    items = OwnerOrderSerializer(many=True)


class OwnerCustomerSerializer(serializers.Serializer):
    """Single customer object for owner customers list responses."""

    id = serializers.IntegerField(read_only=True)
    store_id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    phone = serializers.CharField(read_only=True, allow_blank=True)
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    last_order_at = serializers.DateTimeField(allow_null=True, read_only=True)
    avatar_url = serializers.SerializerMethodField()
    orders_count = serializers.IntegerField(read_only=True)

    def get_avatar_url(self, obj):
        avatar_url = getattr(obj, "avatar_url", "")
        return avatar_url or None


class OwnerCustomersListResponseSerializer(serializers.Serializer):
    """Top-level owner customers list response serializer."""

    store_id = serializers.IntegerField()
    items = OwnerCustomerSerializer(many=True)


class StoreDashboardStatsSerializer(serializers.Serializer):
    """Store dashboard summary stats."""

    total_orders = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_products = serializers.IntegerField()
    total_customers = serializers.IntegerField()


class StoreDashboardRecentOrderSerializer(serializers.Serializer):
    """Recent order item for store dashboard."""

    id = serializers.IntegerField()
    customer_name = serializers.CharField(allow_null=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class StoreDashboardTopProductSerializer(serializers.Serializer):
    """Top product item for store dashboard."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    sales_count = serializers.IntegerField()
    revenue_total = serializers.DecimalField(max_digits=12, decimal_places=2)


class StoreDashboardResponseSerializer(serializers.Serializer):
    """Top-level store dashboard response serializer."""

    store_id = serializers.IntegerField()
    stats = StoreDashboardStatsSerializer()
    recent_orders = StoreDashboardRecentOrderSerializer(many=True)
    top_products = StoreDashboardTopProductSerializer(many=True)


class OwnerOrderStatusUpdateSerializer(serializers.Serializer):
    """Request serializer for owner order status update."""

    status = serializers.ChoiceField(
        choices=[
            "pending",
            "processing",
            "shipped",
            "delivered",
            "cancelled",
        ]
    )


class CustomerOrderItemCreateSerializer(serializers.Serializer):
    """Customer request item payload for creating an order."""

    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class CustomerOrderCustomerInputSerializer(serializers.Serializer):
    """Customer identity/contact input payload."""

    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)


class CustomerOrderAddressInputSerializer(serializers.Serializer):
    """Customer shipping address input payload."""

    country = serializers.CharField(max_length=100)
    city = serializers.CharField(max_length=100)
    street = serializers.CharField(max_length=255)
    postal_code = serializers.CharField(max_length=30)


class CustomerCreateOrderRequestSerializer(serializers.Serializer):
    """Customer-facing create-order request payload."""

    customer = CustomerOrderCustomerInputSerializer()
    address = CustomerOrderAddressInputSerializer()
    items = CustomerOrderItemCreateSerializer(many=True, allow_empty=False)


class CustomerCreateOrderResponseSerializer(serializers.Serializer):
    """Minimal customer-facing create-order response payload."""

    order_id = serializers.IntegerField()
    status = serializers.CharField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)


class CheckoutFromCartRequestSerializer(serializers.Serializer):
    """Customer-facing checkout-from-cart request payload."""

    customer = CustomerOrderCustomerInputSerializer()
    address = CustomerOrderAddressInputSerializer()


class PublicCartItemSerializer(serializers.Serializer):
    """Public cart item representation."""

    product_id = serializers.IntegerField()
    name = serializers.CharField()
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantity = serializers.IntegerField(min_value=1)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2)


class PublicCartResponseSerializer(serializers.Serializer):
    """Public cart response payload."""

    cart_token = serializers.CharField()
    store_id = serializers.IntegerField()
    items = PublicCartItemSerializer(many=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2)


class PublicCartAddItemRequestSerializer(serializers.Serializer):
    """Request payload for adding an item to public cart."""

    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class PublicCartUpdateItemRequestSerializer(serializers.Serializer):
    """Request payload for updating cart item quantity."""

    quantity = serializers.IntegerField(min_value=1)
