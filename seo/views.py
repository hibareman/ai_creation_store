from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from users.permissions import TenantAuthenticated

from .selectors import (
    get_owner_category_for_seo,
    get_owner_product_for_seo,
    get_owner_store_for_seo,
)
from .serializers import (
    CategorySEOResponseSerializer,
    ProductSEOResponseSerializer,
    SEOUpdateRequestSerializer,
    StoreSEOResponseSerializer,
)
from .services import (
    get_owner_category_seo_payload,
    get_owner_product_seo_payload,
    get_owner_store_seo_payload,
    get_public_product_seo_payload,
    get_public_store_seo_payload,
    update_owner_category_seo,
    update_owner_product_seo,
    update_owner_store_seo,
)


DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Bad request"),
    401: OpenApiResponse(description="Unauthorized"),
    403: OpenApiResponse(description="Permission denied"),
    404: OpenApiResponse(description="Not found"),
}


class OwnerStoreScopedSEOMixin:
    def _get_owner_store_or_404(self):
        store_id = self.kwargs["store_id"]
        tenant_id = getattr(self.request, "tenant_id", None)
        store = get_owner_store_for_seo(
            store_id=store_id,
            tenant_id=tenant_id,
            user_id=getattr(self.request.user, "id", None),
        )
        if not store:
            raise NotFound("Store not found")
        return store


@extend_schema_view(
    get=extend_schema(
        summary="Get owner store SEO",
        description="Retrieve SEO metadata for a tenant-owned store.",
        tags=["SEO"],
        responses={200: StoreSEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    put=extend_schema(
        summary="Update owner store SEO",
        description="Replace SEO metadata for a tenant-owned store.",
        tags=["SEO"],
        request=SEOUpdateRequestSerializer,
        responses={200: StoreSEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update owner store SEO",
        description="Partially update SEO metadata for a tenant-owned store.",
        tags=["SEO"],
        request=SEOUpdateRequestSerializer,
        responses={200: StoreSEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreSEODetailView(OwnerStoreScopedSEOMixin, generics.GenericAPIView):
    permission_classes = [TenantAuthenticated]
    serializer_class = StoreSEOResponseSerializer

    def get(self, request, *args, **kwargs):
        store = self._get_owner_store_or_404()
        payload = get_owner_store_seo_payload(store=store, user=request.user)
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)

    def _update(self, request):
        store = self._get_owner_store_or_404()
        request_serializer = SEOUpdateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        payload = update_owner_store_seo(
            store=store,
            seo_data=request_serializer.validated_data["seo"],
            user=request.user,
        )
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        return self._update(request)

    def patch(self, request, *args, **kwargs):
        return self._update(request)


@extend_schema_view(
    get=extend_schema(
        summary="Get owner product SEO",
        description="Retrieve SEO metadata for one product in a tenant-owned store.",
        tags=["SEO"],
        responses={200: ProductSEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    put=extend_schema(
        summary="Update owner product SEO",
        description="Replace SEO metadata for one product in a tenant-owned store.",
        tags=["SEO"],
        request=SEOUpdateRequestSerializer,
        responses={200: ProductSEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update owner product SEO",
        description="Partially update SEO metadata for one product in a tenant-owned store.",
        tags=["SEO"],
        request=SEOUpdateRequestSerializer,
        responses={200: ProductSEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class ProductSEODetailView(OwnerStoreScopedSEOMixin, generics.GenericAPIView):
    permission_classes = [TenantAuthenticated]
    serializer_class = ProductSEOResponseSerializer

    def _get_owner_product_or_404(self, store):
        product = get_owner_product_for_seo(
            store_id=store.id,
            product_id=self.kwargs["product_id"],
            tenant_id=store.tenant_id,
        )
        if not product:
            raise NotFound("Product not found")
        return product

    def get(self, request, *args, **kwargs):
        store = self._get_owner_store_or_404()
        product = self._get_owner_product_or_404(store)
        payload = get_owner_product_seo_payload(store=store, product=product, user=request.user)
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)

    def _update(self, request):
        store = self._get_owner_store_or_404()
        product = self._get_owner_product_or_404(store)

        request_serializer = SEOUpdateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        payload = update_owner_product_seo(
            store=store,
            product=product,
            seo_data=request_serializer.validated_data["seo"],
            user=request.user,
        )
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        return self._update(request)

    def patch(self, request, *args, **kwargs):
        return self._update(request)


@extend_schema_view(
    get=extend_schema(
        summary="Get owner category SEO",
        description="Retrieve SEO metadata for one category in a tenant-owned store.",
        tags=["SEO"],
        responses={200: CategorySEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    put=extend_schema(
        summary="Update owner category SEO",
        description="Replace SEO metadata for one category in a tenant-owned store.",
        tags=["SEO"],
        request=SEOUpdateRequestSerializer,
        responses={200: CategorySEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update owner category SEO",
        description="Partially update SEO metadata for one category in a tenant-owned store.",
        tags=["SEO"],
        request=SEOUpdateRequestSerializer,
        responses={200: CategorySEOResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class CategorySEODetailView(OwnerStoreScopedSEOMixin, generics.GenericAPIView):
    permission_classes = [TenantAuthenticated]
    serializer_class = CategorySEOResponseSerializer

    def _get_owner_category_or_404(self, store):
        category = get_owner_category_for_seo(
            store_id=store.id,
            category_id=self.kwargs["category_id"],
            tenant_id=store.tenant_id,
        )
        if not category:
            raise NotFound("Category not found")
        return category

    def get(self, request, *args, **kwargs):
        store = self._get_owner_store_or_404()
        category = self._get_owner_category_or_404(store)
        payload = get_owner_category_seo_payload(store=store, category=category, user=request.user)
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)

    def _update(self, request):
        store = self._get_owner_store_or_404()
        category = self._get_owner_category_or_404(store)

        request_serializer = SEOUpdateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        payload = update_owner_category_seo(
            store=store,
            category=category,
            seo_data=request_serializer.validated_data["seo"],
            user=request.user,
        )
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        return self._update(request)

    def patch(self, request, *args, **kwargs):
        return self._update(request)


@extend_schema_view(
    get=extend_schema(
        summary="Get public store SEO",
        description="Return public-safe SEO metadata for a published active store resolved by subdomain.",
        tags=["Public SEO"],
        responses={200: StoreSEOResponseSerializer, 404: OpenApiResponse(description="Not found")},
    ),
)
class PublicStoreSEOView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = StoreSEOResponseSerializer

    def get(self, request, *args, **kwargs):
        payload = get_public_store_seo_payload(subdomain=self.kwargs["subdomain"])
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Get public product SEO",
        description="Return public-safe SEO metadata for one active product in a published active store resolved by subdomain.",
        tags=["Public SEO"],
        responses={200: ProductSEOResponseSerializer, 404: OpenApiResponse(description="Not found")},
    ),
)
class PublicStoreProductSEOView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductSEOResponseSerializer

    def get(self, request, *args, **kwargs):
        payload = get_public_product_seo_payload(
            subdomain=self.kwargs["subdomain"],
            product_id=self.kwargs["product_id"],
        )
        return Response(self.get_serializer(payload).data, status=status.HTTP_200_OK)

# Create your views here.
