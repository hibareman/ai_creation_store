import logging
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse
from django.shortcuts import get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404

from stores.models import Store
from users.permissions import TenantAuthenticated
from .models import Category
from .serializers import CategorySerializer, CategoryCreateUpdateSerializer
from . import selectors, services

logger = logging.getLogger(__name__)

DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Bad request"),
    403: OpenApiResponse(description="Permission denied"),
    404: OpenApiResponse(description="Not found"),
}


class CategoryStoreAccessMixin:
    """
    Shared store lookup + tenant/owner checks for category endpoints.
    Keeps existing behavior/messages while removing duplicated view logic.
    """

    def get_store(self):
        store_id = self.kwargs.get('store_id')

        try:
            store = get_object_or_404(Store, id=store_id)
        except Http404:
            logger.warning(
                f"Store not found. User: {self.request.user.id}, "
                f"store_id: {store_id}, tenant_id: {self.request.tenant_id}"
            )
            raise NotFound("Store not found")

        # Multi-tenant check: FIRST validate tenant_id
        if store.tenant_id != self.request.tenant_id:
            logger.warning(
                f"Multi-tenant violation: User {self.request.user.id} "
                f"(tenant_id: {self.request.tenant_id}) attempted to access "
                f"store {store_id} (tenant_id: {store.tenant_id})"
            )
            raise PermissionDenied("You do not have access to this store")

        # Then check ownership
        if store.owner_id != self.request.user.id:
            logger.warning(
                f"Ownership violation: User {self.request.user.id} "
                f"attempted to access store {store_id} owned by {store.owner_id}"
            )
            raise PermissionDenied("You do not own this store")

        logger.debug(f"User {self.request.user.id} accessing store {store_id}")
        return store


@extend_schema_view(
    get=extend_schema(
        summary="List categories",
        description="List categories for a tenant-owned store.",
        tags=["Categories"],
        responses={200: CategorySerializer(many=True), **DOC_ERROR_RESPONSES},
    ),
    post=extend_schema(
        summary="Create category",
        description="Create a category in a tenant-owned store.",
        tags=["Categories"],
        request=CategoryCreateUpdateSerializer,
        responses={201: CategorySerializer, **DOC_ERROR_RESPONSES},
    ),
)
class CategoryListCreateView(CategoryStoreAccessMixin, generics.ListCreateAPIView):
    """
    API endpoint for listing and creating categories for a store.
    
    GET: List all categories for a specific store (multi-tenant filtered)
    POST: Create a new category in the store
    """
    
    permission_classes = [TenantAuthenticated]
    serializer_class = CategorySerializer
    
    def get_queryset(self):
        """
        Get categories for the store, filtered by tenant_id.
        
        Critical: Always filter by tenant_id before store_id
        """
        store = self.get_store()
        
        return selectors.get_store_categories(store)
    
    def get_serializer_context(self):
        """
        Add store context to serializer for validation.
        """
        context = super().get_serializer_context()
        context['store'] = self.get_store()
        return context
    
    def post(self, request, *args, **kwargs):
        """
        Create a new category.
        
        Request body:
        {
            "name": "Electronics",
            "description": "Electronic devices and gadgets"
        }
        """
        store = self.get_store()
        
        serializer = CategoryCreateUpdateSerializer(
            data=request.data,
            context=self.get_serializer_context()
        )
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            category = services.create_category(
                store=store,
                name=serializer.validated_data['name'],
                description=serializer.validated_data.get('description', ''),
                user=request.user
            )
            
            logger.info(f"Category created: id={category.id}, store_id={store.id}, user_id={request.user.id}")
            return Response(
                CategorySerializer(category).data,
                status=status.HTTP_201_CREATED
            )
        except (ValidationError, DjangoValidationError) as e:
            logger.warning(f"Category creation validation error: {str(e)}, user_id={request.user.id}, store_id={store.id}")
            return Response(
                {"error": str(e.message) if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


@extend_schema_view(
    get=extend_schema(
        summary="Get category detail",
        description="Retrieve a single category for a tenant-owned store.",
        tags=["Categories"],
        responses={200: CategorySerializer, **DOC_ERROR_RESPONSES},
    ),
    put=extend_schema(
        summary="Update category",
        description="Replace category data in a tenant-owned store.",
        tags=["Categories"],
        request=CategoryCreateUpdateSerializer,
        responses={200: CategorySerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update category",
        description="Partially update category data in a tenant-owned store.",
        tags=["Categories"],
        request=CategoryCreateUpdateSerializer,
        responses={200: CategorySerializer, **DOC_ERROR_RESPONSES},
    ),
    delete=extend_schema(
        summary="Delete category",
        description="Delete a category from a tenant-owned store.",
        tags=["Categories"],
        responses={
            204: OpenApiResponse(description="Category deleted successfully."),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class CategoryRetrieveUpdateDestroyView(CategoryStoreAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    API endpoint for retrieving, updating, and deleting a specific category.
    
    GET: Retrieve category details
    PUT/PATCH: Update category
    DELETE: Delete category (with validation for linked products)
    """
    
    permission_classes = [TenantAuthenticated]
    serializer_class = CategorySerializer
    
    def get_queryset(self):
        """
        Get categories for the store, filtered by tenant_id.
        """
        store = self.get_store()
        
        return selectors.get_store_categories(store)
    
    def get_serializer_context(self):
        """
        Add store context to serializer for validation.
        """
        context = super().get_serializer_context()
        context['store'] = self.get_store()
        return context
    
    def get_object(self):
        """
        Retrieve category with validation.
        """
        store = self.get_store()
        category_id = self.kwargs.get('category_id')
        
        try:
            category = selectors.get_category_by_id(category_id, store)
            return category
        except ObjectDoesNotExist:
            raise NotFound("Category not found")
    
    def put(self, request, *args, **kwargs):
        """
        Full update of category.
        """
        category = self.get_object()
        store = self.get_store()
        
        serializer = CategoryCreateUpdateSerializer(
            category,
            data=request.data,
            context=self.get_serializer_context(),
            partial=False
        )
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            updated_category = services.update_category(
                category=category,
                name=serializer.validated_data.get('name'),
                description=serializer.validated_data.get('description'),
                user=request.user
            )
            
            return Response(
                CategorySerializer(updated_category).data,
                status=status.HTTP_200_OK
            )
        except (ValidationError, DjangoValidationError) as e:
            return Response(
                {"error": str(e.message) if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def patch(self, request, *args, **kwargs):
        """
        Partial update of category.
        """
        category = self.get_object()
        
        serializer = CategoryCreateUpdateSerializer(
            category,
            data=request.data,
            context=self.get_serializer_context(),
            partial=True
        )
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            updated_category = services.update_category(
                category=category,
                name=serializer.validated_data.get('name'),
                description=serializer.validated_data.get('description'),
                user=request.user
            )
            
            return Response(
                CategorySerializer(updated_category).data,
                status=status.HTTP_200_OK
            )
        except (ValidationError, DjangoValidationError) as e:
            return Response(
                {"error": str(e.message) if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def delete(self, request, *args, **kwargs):
        """
        Delete category with validation.
        
        Returns 409 Conflict if category has linked products.
        """
        category = self.get_object()
        
        try:
            services.delete_category(category, user=request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except (ValidationError, DjangoValidationError) as e:
            return Response(
                {"error": str(e.message) if hasattr(e, 'message') else str(e)},
                status=status.HTTP_409_CONFLICT
            )
