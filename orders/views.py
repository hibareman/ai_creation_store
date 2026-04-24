from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer

from stores.selectors import get_public_store_by_subdomain, get_store_by_id
from users.permissions import TenantAuthenticated

from .serializers import (
    CheckoutFromCartRequestSerializer,
    CustomerCreateOrderRequestSerializer,
    CustomerCreateOrderResponseSerializer,
    OwnerCustomersListResponseSerializer,
    OwnerOrderDetailResponseSerializer,
    OwnerOrderDetailSerializer,
    OwnerOrderSerializer,
    OwnerOrdersListResponseSerializer,
    OwnerOrderStatusUpdateSerializer,
    PublicCartAddItemRequestSerializer,
    PublicCartResponseSerializer,
    PublicCartUpdateItemRequestSerializer,
    StoreDashboardResponseSerializer,
)
from .services import (
    add_item_to_public_cart,
    checkout_cart_to_order,
    clear_public_cart,
    create_customer_order,
    get_public_cart_payload,
    get_owner_order_detail,
    get_order_by_id_for_owner,
    get_owner_customers_payload,           
    get_owner_orders_payload,
    get_store_dashboard_payload,
    remove_item_from_public_cart,
    update_order_status,
    update_public_cart_item_quantity,
)

DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Bad request"),
    403: OpenApiResponse(description="Permission denied"),
    404: OpenApiResponse(description="Not found"),
}


class OwnerStoreScopedMixin:
    """
    Shared store resolver for owner endpoints with strict tenant scoping.
    """

    def get_store(self):
        store_id = self.kwargs["store_id"]
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise NotFound("Store not found")

        store = get_store_by_id(store_id, tenant_id=tenant_id)
        if not store:
            raise NotFound("Store not found")
        return store


@extend_schema_view(
    get=extend_schema(
        summary="Get owner store dashboard",
        description="Return dashboard stats, recent orders, and top products for the authenticated owner's tenant-scoped store.",
        tags=["Orders"],
        responses={200: StoreDashboardResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreOwnerDashboardView(OwnerStoreScopedMixin, generics.GenericAPIView):
    """
    Owner dashboard endpoint.
    GET /api/stores/{store_id}/dashboard/
    """

    permission_classes = [TenantAuthenticated]
    serializer_class = StoreDashboardResponseSerializer

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        payload = get_store_dashboard_payload(store, user=request.user)

        serializer = self.get_serializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="List owner store customers",
        description="Return aggregated customers data for the authenticated owner's tenant-scoped store.",
        tags=["Orders"],
        responses={200: OwnerCustomersListResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreOwnerCustomersListView(OwnerStoreScopedMixin, generics.GenericAPIView):
    """
    Owner customers list endpoint.
    GET /api/stores/{store_id}/customers/
    """

    permission_classes = [TenantAuthenticated]
    serializer_class = OwnerCustomersListResponseSerializer

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        payload = get_owner_customers_payload(store, user=request.user)

        serializer = self.get_serializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="List owner store orders",
        description="Return orders for the authenticated owner's tenant-scoped store.",
        tags=["Orders"],
        responses={200: OwnerOrdersListResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreOwnerOrdersListView(OwnerStoreScopedMixin, generics.GenericAPIView):
    """
    Owner orders list endpoint.
    GET /api/stores/{store_id}/orders/
    """

    permission_classes = [TenantAuthenticated]
    serializer_class = OwnerOrdersListResponseSerializer

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        payload = get_owner_orders_payload(store, user=request.user)

        serializer = self.get_serializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Get owner order detail",
        description="Return one order detail for the authenticated owner's tenant-scoped store.",
        tags=["Orders"],
        responses={200: OwnerOrderDetailResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreOwnerOrderDetailView(OwnerStoreScopedMixin, generics.GenericAPIView):
    """
    Owner order detail endpoint.
    GET /api/stores/{store_id}/orders/{order_id}/
    """

    permission_classes = [TenantAuthenticated]
    serializer_class = OwnerOrderDetailSerializer

    def get(self, request, *args, **kwargs):
        store = self.get_store()
        order_id = self.kwargs["order_id"]
        order = get_owner_order_detail(store=store, order_id=order_id, user=request.user)
        if not order:
            raise NotFound("Order not found")

        serializer = self.get_serializer(order)
        return Response({"order": serializer.data}, status=status.HTTP_200_OK)


@extend_schema_view(
    patch=extend_schema(
        summary="Update owner order status",
        description="Update status for one order in the authenticated owner's tenant-scoped store.",
        tags=["Orders"],
        request=OwnerOrderStatusUpdateSerializer,
        responses={
            200: inline_serializer(
                name="OwnerOrderStatusUpdateResponse",
                fields={"order": OwnerOrderSerializer()},
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class StoreOwnerOrderStatusUpdateView(OwnerStoreScopedMixin, generics.GenericAPIView):
    """
    Owner order status update endpoint.
    PATCH /api/stores/{store_id}/orders/{order_id}/status/
    """

    permission_classes = [TenantAuthenticated]
    serializer_class = OwnerOrderStatusUpdateSerializer

    def patch(self, request, *args, **kwargs):
        store = self.get_store()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        status_value = serializer.validated_data["status"]

        order_id = self.kwargs["order_id"]
        order = get_order_by_id_for_owner(store.id, store.tenant_id, order_id)
        if not order:
            raise NotFound("Order not found")

        updated_order = update_order_status(
            store=store,
            order=order,
            status=status_value,
            user=request.user,
        )

        order_serializer = OwnerOrderSerializer(updated_order)
        return Response({"order": order_serializer.data}, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Create public order",
        description="Create a customer order for a published active store resolved by subdomain.",
        tags=["Orders"],
        request=CustomerCreateOrderRequestSerializer,
        responses={201: CustomerCreateOrderResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class PublicStoreCreateOrderView(generics.GenericAPIView):
    """
    Public customer-facing create-order endpoint.
    POST /api/public/store/{subdomain}/orders/
    """

    permission_classes = [AllowAny]
    serializer_class = CustomerCreateOrderRequestSerializer

    def post(self, request, *args, **kwargs):
        subdomain = self.kwargs["subdomain"]
        store = get_public_store_by_subdomain(subdomain)
        if not store:
            raise NotFound("Store not found")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = create_customer_order(
            store=store,
            customer_data=serializer.validated_data["customer"],
            address_data=serializer.validated_data["address"],
            items_data=serializer.validated_data["items"],
        )
        response_serializer = CustomerCreateOrderResponseSerializer(payload)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class PublicStoreCartMixin:
    """
    Shared helpers for public cart endpoints.
    """

    def get_public_store(self):
        subdomain = self.kwargs["subdomain"]
        store = get_public_store_by_subdomain(subdomain)
        if not store:
            raise NotFound("Store not found")
        return store

    def get_cart_token(self, request):
        header_token = request.headers.get("X-Cart-Token")
        if header_token:
            return header_token

        query_token = request.query_params.get("cart_token")
        if query_token:
            return query_token

        data = getattr(request, "data", None) or {}
        return data.get("cart_token")

    @staticmethod
    def response_with_cart_token(payload, status_code=status.HTTP_200_OK):
        serializer = PublicCartResponseSerializer(payload)
        response = Response(serializer.data, status=status_code)
        response["X-Cart-Token"] = payload["cart_token"]
        return response


@extend_schema_view(
    get=extend_schema(
        summary="Get public cart",
        description="Return cart contents for a published active store resolved by subdomain.",
        tags=["Orders"],
        responses={200: PublicCartResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    delete=extend_schema(
        summary="Clear public cart",
        description="Clear all items from a store-scoped public cart.",
        tags=["Orders"],
        responses={
            204: OpenApiResponse(description="Cart cleared successfully."),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class PublicStoreCartView(PublicStoreCartMixin, generics.GenericAPIView):
    """
    Public cart view/clear endpoint.
    GET /api/public/store/{subdomain}/cart/
    DELETE /api/public/store/{subdomain}/cart/
    """

    permission_classes = [AllowAny]
    serializer_class = PublicCartResponseSerializer

    def get(self, request, *args, **kwargs):
        store = self.get_public_store()
        payload = get_public_cart_payload(
            store=store,
            cart_token=self.get_cart_token(request),
        )
        return self.response_with_cart_token(payload, status_code=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        store = self.get_public_store()
        payload = clear_public_cart(
            store=store,
            cart_token=self.get_cart_token(request),
        )
        return self.response_with_cart_token(payload, status_code=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Add item to public cart",
        description="Add a product to a store-scoped public cart resolved by subdomain and cart token.",
        tags=["Orders"],
        request=PublicCartAddItemRequestSerializer,
        responses={201: PublicCartResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class PublicStoreCartItemsView(PublicStoreCartMixin, generics.GenericAPIView):
    """
    Public cart add-item endpoint.
    POST /api/public/store/{subdomain}/cart/items/
    """

    permission_classes = [AllowAny]
    serializer_class = PublicCartAddItemRequestSerializer

    def post(self, request, *args, **kwargs):
        store = self.get_public_store()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = add_item_to_public_cart(
            store=store,
            product_id=serializer.validated_data["product_id"],
            quantity=serializer.validated_data["quantity"],
            cart_token=self.get_cart_token(request),
        )
        return self.response_with_cart_token(payload, status_code=status.HTTP_201_CREATED)


@extend_schema_view(
    patch=extend_schema(
        summary="Update public cart item quantity",
        description="Replace quantity for one product in a store-scoped public cart.",
        tags=["Orders"],
        request=PublicCartUpdateItemRequestSerializer,
        responses={200: PublicCartResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    delete=extend_schema(
        summary="Remove item from public cart",
        description="Remove one product from a store-scoped public cart.",
        tags=["Orders"],
        responses={
            204: OpenApiResponse(description="Cart item removed successfully."),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class PublicStoreCartItemDetailView(PublicStoreCartMixin, generics.GenericAPIView):
    """
    Public cart update/remove-item endpoint.
    PATCH /api/public/store/{subdomain}/cart/items/{product_id}/
    DELETE /api/public/store/{subdomain}/cart/items/{product_id}/
    """

    permission_classes = [AllowAny]
    serializer_class = PublicCartUpdateItemRequestSerializer

    def patch(self, request, *args, **kwargs):
        store = self.get_public_store()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = update_public_cart_item_quantity(
            store=store,
            product_id=self.kwargs["product_id"],
            quantity=serializer.validated_data["quantity"],
            cart_token=self.get_cart_token(request),
        )
        return self.response_with_cart_token(payload, status_code=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        store = self.get_public_store()
        payload = remove_item_from_public_cart(
            store=store,
            product_id=self.kwargs["product_id"],
            cart_token=self.get_cart_token(request),
        )
        return self.response_with_cart_token(payload, status_code=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Checkout public cart",
        description="Create an order from cart items for a published active store resolved by subdomain.",
        tags=["Orders"],
        request=CheckoutFromCartRequestSerializer,
        responses={201: CustomerCreateOrderResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class PublicStoreCartCheckoutView(PublicStoreCartMixin, generics.GenericAPIView):
    """
    Public cart checkout endpoint.
    POST /api/public/store/{subdomain}/cart/checkout/
    """

    permission_classes = [AllowAny]
    serializer_class = CheckoutFromCartRequestSerializer

    def post(self, request, *args, **kwargs):
        store = self.get_public_store()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = checkout_cart_to_order(
            store=store,
            cart_token=self.get_cart_token(request),
            customer_data=serializer.validated_data["customer"],
            address_data=serializer.validated_data["address"],
        )
        response_serializer = CustomerCreateOrderResponseSerializer(payload)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
