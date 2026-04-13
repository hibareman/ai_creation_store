"""
Views for Products API

MULTI-TENANT RULE: Every view must:
1. Extract tenant_id from request context (middleware)
2. Get store from current user
3. Pass both to services for validation
4. Return only the user's data
"""

import logging
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.core.exceptions import ValidationError

from stores.models import Store
from users.permissions import TenantAuthenticated
from .models import Product, ProductImage
from .serializers import (
    ProductListSerializer, ProductDetailSerializer,
    ProductCreateSerializer, ProductUpdateSerializer,
    ProductImageSerializer, InventoryUpdateSerializer
)
from . import selectors
from . import services

logger = logging.getLogger(__name__)


class ProductStoreAccessMixin:
    """
    Shared authorization helper for product-layer endpoints.

    Rules:
    - store.tenant_id must match request.tenant_id
    - store.owner_id must match request.user.id
    """

    def get_store(self):
        if hasattr(self, '_validated_store'):
            return self._validated_store

        store_id = self.kwargs.get('store_id')
        store = get_object_or_404(Store, id=store_id)

        if store.tenant_id != getattr(self.request, 'tenant_id', None):
            raise PermissionDenied("You do not have access to this store")

        if store.owner_id != self.request.user.id:
            raise PermissionDenied("You do not own this store")

        self._validated_store = store
        return store

    def get_store_product(self):
        store = self.get_store()
        product_id = self.kwargs.get('product_id')

        try:
            return selectors.get_product_by_id(
                product_id=product_id,
                store_id=store.id,
                tenant_id=store.tenant_id
            )
        except Product.DoesNotExist:
            raise Http404("Product not found")


class ProductListCreateView(ProductStoreAccessMixin, generics.ListCreateAPIView):
    """
    GET: List all products for current store
    POST: Create a new product
    
    MULTI-TENANT: Filters by current store and tenant_id
    """
    permission_classes = [TenantAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ProductCreateSerializer
        return ProductListSerializer
    
    def get_queryset(self):
        """
        MULTI-TENANT: Return products only from current store/tenant
        SECURITY: Uses store_id and tenant_id from user context
        """
        store = self.get_store()

        return selectors.get_products_by_store(
            store_id=store.id,
            tenant_id=store.tenant_id
        )
    
    def create(self, request, *args, **kwargs):
        """
        Create product with business logic validation.
        
        MULTI-TENANT: tenant_id comes from middleware/request context
        """
        store = self.get_store()
        
        # Validate serializer
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Use service for business logic
        try:
            product = services.create_product(
                user=request.user,
                store=store,
                name=serializer.validated_data['name'],
                price=serializer.validated_data['price'],
                sku=serializer.validated_data['sku'],
                description=serializer.validated_data.get('description', ''),
                category=serializer.validated_data.get('category'),
                status=serializer.validated_data.get('status', 'active')
            )
            
            response_serializer = ProductDetailSerializer(product)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            return Response(
                {"detail": "Failed to create product"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductDetailView(ProductStoreAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Retrieve product details
    PUT: Update product
    DELETE: Delete product
    
    MULTI-TENANT: Verifies ownership before any operation
    """
    permission_classes = [TenantAuthenticated]
    serializer_class = ProductDetailSerializer
    
    def get_object(self):
        """
        MULTI-TENANT: Get product with ownership verification
        """
        return self.get_store_product()
    
    def get_serializer_class(self):
        if self.request.method == 'PUT' or self.request.method == 'PATCH':
            return ProductUpdateSerializer
        return ProductDetailSerializer
    
    def update(self, request, *args, **kwargs):
        """
        Update product with business logic validation.
        
        MULTI-TENANT: Verifies ownership in service layer
        """
        product = self.get_object()
        store = self.get_store()
        
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated = services.update_product(
                user=request.user,
                store=store,
                product=product,
                **serializer.validated_data
            )
            
            response_serializer = ProductDetailSerializer(updated)
            return Response(response_serializer.data)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            logger.error(f"Error updating product: {str(e)}")
            return Response(
                {"detail": "Failed to update product"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def destroy(self, request, *args, **kwargs):
        """
        Delete product with ownership verification.
        
        MULTI-TENANT: Verifies ownership in service layer
        """
        product = self.get_object()
        store = self.get_store()
        
        try:
            services.delete_product(
                user=request.user,
                store=store,
                product=product,
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except Exception as e:
            logger.error(f"Error deleting product: {str(e)}")
            return Response(
                {"detail": "Failed to delete product"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductImageView(ProductStoreAccessMixin, generics.ListCreateAPIView):
    """
    GET: List all images for a product
    POST: Add new image to product
    
    MULTI-TENANT: Verifies product ownership before any operation
    """
    permission_classes = [TenantAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = ProductImageSerializer
    
    def get_queryset(self):
        """
        MULTI-TENANT: Get images only if product belongs to user's store
        """
        product_id = self.kwargs.get('product_id')
        store = self.get_store()
        
        try:
            # Verify product ownership first
            selectors.get_product_by_id(
                product_id=product_id,
                store_id=store.id,
                tenant_id=store.tenant_id
            )
            return selectors.get_product_images(
                product_id=product_id,
                store_id=store.id,
                tenant_id=store.tenant_id
            )
        except Product.DoesNotExist:
            return ProductImage.objects.none()
    
    def create(self, request, *args, **kwargs):
        """
        Add image to product with ownership verification.
        """
        product_id = kwargs.get('product_id')
        store = self.get_store()
        
        try:
            product = selectors.get_product_by_id(
                product_id=product_id,
                store_id=store.id,
                tenant_id=store.tenant_id
            )
        except Product.DoesNotExist:
            return Response(
                {"detail": "Product not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            image = services.add_product_image(
                user=request.user,
                store=store,
                product=product,
                image_url=serializer.validated_data.get('image_url'),
                image_file=serializer.validated_data.get('image_file')
            )
            
            response_serializer = ProductImageSerializer(image)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )


class ProductImageDetailView(ProductStoreAccessMixin, generics.DestroyAPIView):
    """
    DELETE: Delete a product image
    
    MULTI-TENANT: Verifies product ownership before deletion
    """
    permission_classes = [TenantAuthenticated]
    
    def get_object(self):
        """
        MULTI-TENANT: Get image with ownership verification
        """
        image_id = self.kwargs.get('image_id')
        product = self.get_store_product()
        return get_object_or_404(ProductImage, id=image_id, product=product)
    
    def destroy(self, request, *args, **kwargs):
        """Delete image with ownership verification"""
        image = self.get_object()
        store = self.get_store()
        
        try:
            services.delete_product_image(
                user=request.user,
                store=store,
                product_image=image,
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )


class InventoryUpdateView(ProductStoreAccessMixin, generics.UpdateAPIView):
    """
    PUT: Update product inventory
    
    MULTI-TENANT: Verifies product ownership before updating
    """
    permission_classes = [TenantAuthenticated]
    serializer_class = InventoryUpdateSerializer
    
    def get_object(self):
        """
        MULTI-TENANT: Get product with ownership verification
        """
        return self.get_store_product()
    
    def update(self, request, *args, **kwargs):
        """Update inventory with business logic validation"""
        product = self.get_object()
        store = self.get_store()
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            inventory = services.update_inventory(
                user=request.user,
                store=store,
                product=product,
                stock_quantity=serializer.validated_data['stock_quantity']
            )
            
            from .serializers import InventorySerializer
            response_serializer = InventorySerializer(inventory)
            return Response(response_serializer.data)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
