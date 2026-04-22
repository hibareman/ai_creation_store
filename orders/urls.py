from django.urls import path

from .views import (
    PublicStoreCartItemDetailView,
    PublicStoreCartItemsView,
    PublicStoreCartCheckoutView,
    PublicStoreCartView,
    PublicStoreCreateOrderView,
    StoreOwnerCustomersListView,
    StoreOwnerDashboardView,
    StoreOwnerOrderDetailView,
    StoreOwnerOrdersListView,
    StoreOwnerOrderStatusUpdateView,
)

app_name = "orders"

urlpatterns = [
    path("public/store/<slug:subdomain>/orders/", PublicStoreCreateOrderView.as_view(), name="public-store-create-order"),
    path("public/store/<slug:subdomain>/cart/", PublicStoreCartView.as_view(), name="public-store-cart"),
    path(
        "public/store/<slug:subdomain>/cart/checkout/",
        PublicStoreCartCheckoutView.as_view(),
        name="public-store-cart-checkout",
    ),
    path("public/store/<slug:subdomain>/cart/items/", PublicStoreCartItemsView.as_view(), name="public-store-cart-items"),
    path(
        "public/store/<slug:subdomain>/cart/items/<int:product_id>/",
        PublicStoreCartItemDetailView.as_view(),
        name="public-store-cart-item-detail",
    ),
    path("stores/<int:store_id>/dashboard/", StoreOwnerDashboardView.as_view(), name="owner-store-dashboard"),
    path("stores/<int:store_id>/customers/", StoreOwnerCustomersListView.as_view(), name="owner-store-customers"),
    path("stores/<int:store_id>/orders/", StoreOwnerOrdersListView.as_view(), name="owner-store-orders"),
    path(
        "stores/<int:store_id>/orders/<int:order_id>/",
        StoreOwnerOrderDetailView.as_view(),
        name="owner-store-order-detail",
    ),
    path(
        "stores/<int:store_id>/orders/<int:order_id>/status/",
        StoreOwnerOrderStatusUpdateView.as_view(),
        name="owner-store-order-status-update",
    ),
]
