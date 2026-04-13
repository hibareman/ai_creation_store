from django.urls import path
from .views import (
    ProductListCreateView,
    ProductDetailView,
    ProductImageView,
    ProductImageDetailView,
    InventoryUpdateView
)

# Product URLs: /api/products/
app_name = 'products'

urlpatterns = [
    # Product CRUD
    path(
        '<int:store_id>/products/',
        ProductListCreateView.as_view(),
        name='product-list-create'
    ),
    path(
        '<int:store_id>/products/<int:product_id>/',
        ProductDetailView.as_view(),
        name='product-detail'
    ),
    
    # Product Images
    path(
        '<int:store_id>/products/<int:product_id>/images/',
        ProductImageView.as_view(),
        name='product-image-list-create'
    ),
    path(
        '<int:store_id>/products/<int:product_id>/images/<int:image_id>/',
        ProductImageDetailView.as_view(),
        name='product-image-delete'
    ),
    
    # Inventory Management
    path(
        '<int:store_id>/products/<int:product_id>/inventory/',
        InventoryUpdateView.as_view(),
        name='inventory-update'
    ),
]
