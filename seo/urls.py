from django.urls import path

from .views import (
    CategorySEODetailView,
    ProductSEODetailView,
    PublicStoreProductSEOView,
    PublicStoreSEOView,
    StoreSEODetailView,
)


urlpatterns = [
    path("stores/<int:store_id>/seo/", StoreSEODetailView.as_view(), name="seo-store-detail"),
    path(
        "products/<int:store_id>/products/<int:product_id>/seo/",
        ProductSEODetailView.as_view(),
        name="seo-product-detail",
    ),
    path(
        "categories/<int:store_id>/categories/<int:category_id>/seo/",
        CategorySEODetailView.as_view(),
        name="seo-category-detail",
    ),
    path("public/store/<slug:subdomain>/seo/", PublicStoreSEOView.as_view(), name="seo-public-store-detail"),
    path(
        "public/store/<slug:subdomain>/products/<int:product_id>/seo/",
        PublicStoreProductSEOView.as_view(),
        name="seo-public-store-product-detail",
    ),
]
