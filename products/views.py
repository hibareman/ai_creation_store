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
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.core.exceptions import ValidationError

from stores.models import Store
from .models import Product, ProductImage
from .serializers import (
    ProductListSerializer, ProductDetailSerializer,
    ProductCreateSerializer, ProductUpdateSerializer,
    ProductImageSerializer, InventoryUpdateSerializer
)
from . import selectors
from . import services

logger = logging.getLogger(__name__)


class ProductListCreateView(generics.ListCreateAPIView):
    """
    GET: List all products for current store
    POST: Create a new product
    
    MULTI-TENANT: Filters by current store and tenant_id
    """
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ProductCreateSerializer
        return ProductListSerializer
    
    def get_queryset(self):
        """
        MULTI-TENANT: Return products only from current store/tenant
        SECURITY: Uses store_id and tenant_id from user context
        """
        store_id = self.kwargs.get('store_id')
        tenant_id = getattr(self.request, 'tenant_id', None)
        
        if not tenant_id:
            return Product.objects.none()
        
        return selectors.get_products_by_store(
            store_id=store_id,
            tenant_id=tenant_id
        )
    
    def create(self, request, *args, **kwargs):
        """
        Create product with business logic validation.
        
        MULTI-TENANT: tenant_id comes from middleware/request context
        """
        store_id = kwargs.get('store_id')
        tenant_id = getattr(request, 'tenant_id', None)
        
        if not tenant_id:
            return Response(
                {"detail": "No tenant context found"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get store with tenant verification
        try:
            store = Store.objects.get(id=store_id, tenant_id=tenant_id)
        except Store.DoesNotExist:
            logger.warning(
                f"Unauthorized store access attempt: store_id={store_id}, "
                f"tenant_id={tenant_id}"
            )
            return Response(
                {"detail": "Store not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Validate serializer
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Use service for business logic
        try:
            product = services.create_product(
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
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            return Response(
                {"detail": "Failed to create product"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Retrieve product details
    PUT: Update product
    DELETE: Delete product
    
    MULTI-TENANT: Verifies ownership before any operation
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ProductDetailSerializer
    
    def get_object(self):
        """
        MULTI-TENANT: Get product with ownership verification
        """
        product_id = self.kwargs.get('product_id')
        store_id = self.kwargs.get('store_id')
        tenant_id = getattr(self.request, 'tenant_id', None)
        
        if not tenant_id:
            self.permission_denied(self.request, "No tenant context")
        
        try:
            return selectors.get_product_by_id(
                product_id=product_id,
                store_id=store_id,
                tenant_id=tenant_id
            )
        except Product.DoesNotExist:
            raise Http404("Product not found")
    
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
        store_id = kwargs.get('store_id')
        tenant_id = getattr(request, 'tenant_id', None)
        
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        try:
            updated = services.update_product(
                product=product,
                store_id=store_id,
                tenant_id=tenant_id,
                **serializer.validated_data
            )
            
            response_serializer = ProductDetailSerializer(updated)
            return Response(response_serializer.data)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
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
        store_id = kwargs.get('store_id')
        tenant_id = getattr(request, 'tenant_id', None)
        
        try:
            services.delete_product(
                product=product,
                store_id=store_id,
                tenant_id=tenant_id
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error deleting product: {str(e)}")
            return Response(
                {"detail": "Failed to delete product"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductImageView(generics.ListCreateAPIView):
    """
    GET: List all images for a product
    POST: Add new image to product
    
    MULTI-TENANT: Verifies product ownership before any operation
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = ProductImageSerializer
    
    def get_queryset(self):
        """
        MULTI-TENANT: Get images only if product belongs to user's store
        """
        product_id = self.kwargs.get('product_id')
        store_id = self.kwargs.get('store_id')
        tenant_id = getattr(self.request, 'tenant_id', None)
        
        if not tenant_id:
            return ProductImage.objects.none()
        
        try:
            # Verify product ownership first
            selectors.get_product_by_id(
                product_id=product_id,
                store_id=store_id,
                tenant_id=tenant_id
            )
            return selectors.get_product_images(
                product_id=product_id,
                store_id=store_id,
                tenant_id=tenant_id
            )
        except Product.DoesNotExist:
            return ProductImage.objects.none()
    
    def create(self, request, *args, **kwargs):
        """
        Add image to product with ownership verification.
        """
        product_id = kwargs.get('product_id')
        store_id = kwargs.get('store_id')
        tenant_id = getattr(request, 'tenant_id', None)
        
        if not tenant_id:
            return Response(
                {"detail": "No tenant context"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            product = selectors.get_product_by_id(
                product_id=product_id,
                store_id=store_id,
                tenant_id=tenant_id
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
                product=product,
                store_id=store_id,
                tenant_id=tenant_id,
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


class ProductImageDetailView(generics.DestroyAPIView):
    """
    DELETE: Delete a product image
    
    MULTI-TENANT: Verifies product ownership before deletion
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self):
        """
        MULTI-TENANT: Get image with ownership verification
        """
        image_id = self.kwargs.get('image_id')
        store_id = self.kwargs.get('store_id')
        tenant_id = getattr(self.request, 'tenant_id', None)
        
        if not tenant_id:
            self.permission_denied(self.request, "No tenant context")
        
        image = get_object_or_404(ProductImage, id=image_id)
        
        # Verify image belongs to product in this store/tenant
        if (image.product.store_id != store_id or
            image.product.tenant_id != tenant_id):
            
            logger.warning(
                f"Unauthorized image access: image_id={image_id}, "
                f"attempted_tenant_id={tenant_id}, "
                f"actual_tenant_id={image.product.tenant_id}"
            )
            self.permission_denied(self.request, "Cannot access this image")
        
        return image
    
    def destroy(self, request, *args, **kwargs):
        """Delete image with ownership verification"""
        image = self.get_object()
        store_id = kwargs.get('store_id')
        tenant_id = getattr(request, 'tenant_id', None)
        
        try:
            services.delete_product_image(
                product_image=image,
                store_id=store_id,
                tenant_id=tenant_id
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except ValidationError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class InventoryUpdateView(generics.UpdateAPIView):
    """
    PUT: Update product inventory
    
    MULTI-TENANT: Verifies product ownership before updating
    """
    permission_classes = [IsAuthenticated]
    serializer_class = InventoryUpdateSerializer
    
    def get_object(self):
        """
        MULTI-TENANT: Get product with ownership verification
        """
        product_id = self.kwargs.get('product_id')
        store_id = self.kwargs.get('store_id')
        tenant_id = getattr(self.request, 'tenant_id', None)
        
        if not tenant_id:
            self.permission_denied(self.request, "No tenant context")
        
        try:
            return selectors.get_product_by_id(
                product_id=product_id,
                store_id=store_id,
                tenant_id=tenant_id
            )
        except Product.DoesNotExist:
            raise Http404("Product not found")
    
    def update(self, request, *args, **kwargs):
        """Update inventory with business logic validation"""
        product = self.get_object()
        store_id = kwargs.get('store_id')
        tenant_id = getattr(request, 'tenant_id', None)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            inventory = services.update_inventory(
                product=product,
                store_id=store_id,
                tenant_id=tenant_id,
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
