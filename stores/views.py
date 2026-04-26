import logging
from rest_framework import generics, status, serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer, OpenApiResponse
from django.core.exceptions import ValidationError
from .models import Store, StoreSettings, StoreDomain
from .serializers import (
    StoreSerializer,
    StoreSettingsSerializer,
    StoreSettingsUpdateSerializer,
    StoreSettingsUpdateRequestSerializer,
    StoreDomainSerializer,
    CheckSlugSerializer,
    SuggestSlugSerializer,
    PublishStoreRequestSerializer,
    PublicStoreSerializer,
    StorePublishStateSerializer,
    SetStoreSubdomainRequestSerializer,
    StoreSubdomainResponseSerializer,
)
from .services import (
    create_store,
    update_store,
    update_store_settings,
    add_domain,
    update_domain,
    delete_domain,
    is_slug_available,
    suggest_slugs,
    publish_store,
    unpublish_store,
    set_store_subdomain,
)
from .selectors import (
    get_user_stores,
    get_store_by_id,
    get_store_domains_by_store_id,
    get_public_store_by_subdomain,
)
from users.permissions import TenantAuthenticated

logger = logging.getLogger(__name__)

DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Bad request"),
    403: OpenApiResponse(description="Permission denied"),
    404: OpenApiResponse(description="Not found"),
}


class StoreAccessMixin:
    """
    Minimal shared helpers for store fetch + access checks.
    """

    def _get_store_or_not_found(self, store_id):
        from rest_framework.exceptions import NotFound
        store = get_store_by_id(store_id)
        if not store:
            raise NotFound("Store not found")
        return store

    def _has_store_access(self, request, store):
        return (
            store.tenant_id == request.tenant_id and
            store.owner_id == request.user.id
        )

    def _enforce_store_access(self, request, store):
        from rest_framework.exceptions import PermissionDenied
        if store.tenant_id != request.tenant_id:
            raise PermissionDenied("You do not have access to this store")
        if store.owner_id != request.user.id:
            raise PermissionDenied("You do not own this store")

# Create store
@extend_schema_view(
    get=extend_schema(
        summary="List stores",
        description="Return all stores visible to the authenticated user in tenant scope.",
        tags=["Stores"],
        responses={200: StoreSerializer(many=True), **DOC_ERROR_RESPONSES},
    ),
    post=extend_schema(
        summary="Create store",
        description="Create a new store owned by the authenticated user.",
        tags=["Stores"],
        request=StoreSerializer,
        responses={201: StoreSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreListCreateView(generics.ListCreateAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == 'Super Admin':
            return Store.objects.all()
        return get_user_stores(self.request.user)

    def perform_create(self, serializer):
        owner = self.request.user
        logger.debug(f"User {owner.id} (tenant_id: {self.request.tenant_id}) creating store")
        store = create_store(
            owner=owner,
            name=serializer.validated_data['name'],
            description=serializer.validated_data.get('description', ''),
            # New stores must start in setup state (not active).
            status='setup',
            slug=serializer.validated_data.get('slug')
        )
        logger.info(f"Store created: id={store.id}, owner={owner.id}, tenant_id={store.tenant_id}")
        serializer.instance = store

# Update store
@extend_schema_view(
    put=extend_schema(
        summary="Update store",
        description="Replace store data for a tenant-owned store.",
        tags=["Stores"],
        request=StoreSerializer,
        responses={200: StoreSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update store",
        description="Partially update store data for a tenant-owned store.",
        tags=["Stores"],
        request=StoreSerializer,
        responses={200: StoreSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class UpdateStoreView(generics.UpdateAPIView):
    serializer_class = StoreSerializer
    permission_classes = [TenantAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        # Return all stores for permission checking
        return Store.objects.all()
    
    def get_object(self):
        """Override get_object to add proper permission checks before returning 404"""
        try:
            store = super().get_object()
        except Exception:
            # Store not found
            logger.warning(f"Store not found. User: {self.request.user.id}, tenant_id: {self.request.tenant_id}")
            raise
        
        # Check tenant_id match FIRST
        if store.tenant_id != self.request.tenant_id:
            logger.warning(f"Multi-tenant violation: User {self.request.user.id} (tenant_id: {self.request.tenant_id}) attempted to update store {store.id} (tenant_id: {store.tenant_id})")
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have access to this store")
        
        # Check ownership
        if store.owner_id != self.request.user.id:
            logger.warning(f"Ownership violation: User {self.request.user.id} attempted to update store {store.id} owned by {store.owner_id}")
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this store")
        
        logger.debug(f"User {self.request.user.id} updating store {store.id}")
        return store

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        store = self.get_object()

        serializer = self.get_serializer(store, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_store = update_store(store=store, **serializer.validated_data)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = self.get_serializer(updated_store)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

# Delete store
@extend_schema_view(
    delete=extend_schema(
        summary="Delete store",
        description="Delete a tenant-owned store.",
        tags=["Stores"],
        responses={
            204: OpenApiResponse(description="Store deleted successfully."),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class DestroyStoreView(generics.DestroyAPIView):
    permission_classes = [TenantAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        # Return all stores for permission checking
        return Store.objects.all()
    
    def get_object(self):
        """Override get_object to add proper permission checks before returning 404"""
        try:
            store = super().get_object()
        except Exception:
            # Store not found
            logger.warning(f"Store not found for deletion. User: {self.request.user.id}, tenant_id: {self.request.tenant_id}")
            raise
        
        # Check tenant_id match FIRST
        if store.tenant_id != self.request.tenant_id:
            logger.warning(f"Multi-tenant violation: User {self.request.user.id} (tenant_id: {self.request.tenant_id}) attempted to delete store {store.id} (tenant_id: {store.tenant_id})")
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have access to this store")
        
        # Check ownership
        if store.owner_id != self.request.user.id:
            logger.warning(f"Ownership violation: User {self.request.user.id} attempted to delete store {store.id} owned by {store.owner_id}")
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this store")
        
        logger.info(f"User {self.request.user.id} deleting store {store.id}")
        return store


@extend_schema_view(
    post=extend_schema(
        summary="Check store slug availability",
        description="Check whether a slug can be used for a store.",
        tags=["Stores"],
        request=CheckSlugSerializer,
        responses={
            200: inline_serializer(
                name="CheckSlugAvailabilityResponse",
                fields={
                    "slug": drf_serializers.CharField(),
                    "available": drf_serializers.BooleanField(),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class CheckSlugAvailabilityView(generics.GenericAPIView):
    serializer_class = CheckSlugSerializer
    permission_classes = [TenantAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slug = serializer.validated_data['slug']
        store_id = serializer.validated_data.get('store_id')
        available = is_slug_available(slug, store_id=store_id)

        return Response({
            'slug': slug,
            'available': available,
        }, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Suggest store slugs",
        description="Generate available slug suggestions from a store name.",
        tags=["Stores"],
        request=SuggestSlugSerializer,
        responses={
            200: inline_serializer(
                name="SuggestSlugResponse",
                fields={
                    "name": drf_serializers.CharField(),
                    "suggestions": drf_serializers.ListField(child=drf_serializers.CharField()),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class SuggestSlugView(generics.GenericAPIView):
    serializer_class = SuggestSlugSerializer
    permission_classes = [TenantAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.validated_data['name']
        store_id = serializer.validated_data.get('store_id')
        limit = serializer.validated_data['limit']
        suggestions = suggest_slugs(name, limit=limit, store_id=store_id)

        return Response({
            'name': name,
            'suggestions': suggestions,
        }, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Get public store by subdomain",
        description="Return public-safe store data for the published active store resolved by subdomain.",
        tags=["Public Stores"],
        responses={
            200: inline_serializer(
                name="PublicStoreDetailResponse",
                fields={
                    "store": PublicStoreSerializer(),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class PublicStoreDetailView(generics.GenericAPIView):
    """
    Public store detail by subdomain.
    GET /public/store/{subdomain}/
    """
    serializer_class = PublicStoreSerializer
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        from rest_framework.exceptions import NotFound

        subdomain = self.kwargs['subdomain']
        store = get_public_store_by_subdomain(subdomain)
        if not store:
            raise NotFound("Store not found")

        serializer = self.get_serializer(store)
        return Response({
            "store": serializer.data
        }, status=status.HTTP_200_OK)


@extend_schema_view(
    patch=extend_schema(
        summary="Set store subdomain",
        description=(
            "Set or update only the public subdomain for a tenant-owned store. "
            "This endpoint does not modify slug/storeUrl. Duplicate, invalid, or blank subdomains return 400."
        ),
        tags=["Stores"],
        request=SetStoreSubdomainRequestSerializer,
        responses={
            200: inline_serializer(
                name="SetStoreSubdomainResponse",
                fields={
                    "store": inline_serializer(
                        name="SetStoreSubdomainResponseStore",
                        fields={
                            "subdomain": drf_serializers.CharField(allow_null=True),
                        },
                    ),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class SetStoreSubdomainView(generics.GenericAPIView):
    """
    Set or update a store subdomain for an authenticated tenant user.
    PATCH /api/stores/{store_id}/subdomain/
    """
    serializer_class = SetStoreSubdomainRequestSerializer
    permission_classes = [TenantAuthenticated]

    def patch(self, request, *args, **kwargs):
        from rest_framework.exceptions import NotFound

        store_id = self.kwargs['store_id']
        store = get_store_by_id(store_id, tenant_id=getattr(request, 'tenant_id', None))
        if not store:
            raise NotFound("Store not found")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated_store = set_store_subdomain(
                store=store,
                subdomain=serializer.validated_data["subdomain"],
                user=request.user,
            )
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = StoreSubdomainResponseSerializer({
            "message": "Store subdomain updated successfully",
            "store": {
                "subdomain": updated_store.subdomain,
            },
        })

        return Response({
            "store": response_serializer.data["store"]
        }, status=status.HTTP_200_OK)


@extend_schema_view(
    patch=extend_schema(
        summary="Publish or unpublish store",
        description=(
            "Publish or unpublish a tenant-owned store. Request action must be publish or unpublish. "
            "Publishing requires a valid name, subdomain, active status, and at least one active product. "
            "Response includes current is_published and published_at state."
        ),
        tags=["Stores"],
        request=PublishStoreRequestSerializer,
        responses={
            200: inline_serializer(
                name="StorePublishActionResponse",
                fields={
                    "store": StorePublishStateSerializer(),
                },
            ),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class StorePublishActionView(generics.GenericAPIView):
    """
    Publish or unpublish a store for an authenticated tenant user.
    PATCH /api/stores/{store_id}/publish/
    """
    serializer_class = PublishStoreRequestSerializer
    permission_classes = [TenantAuthenticated]

    def patch(self, request, *args, **kwargs):
        from rest_framework.exceptions import NotFound

        store_id = self.kwargs['store_id']
        store = get_store_by_id(store_id, tenant_id=getattr(request, 'tenant_id', None))
        if not store:
            raise NotFound("Store not found")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]

        try:
            if action == "publish":
                updated_store = publish_store(store, user=request.user)
            else:
                updated_store = unpublish_store(store, user=request.user)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = StorePublishStateSerializer(updated_store)
        return Response({
            "store": response_serializer.data
        }, status=status.HTTP_200_OK)


# StoreSettings Views
@extend_schema_view(
    get=extend_schema(
        summary="Get store settings",
        description=(
            "Retrieve settings for a tenant-owned store. storeUrl maps to the store slug, "
            "while storeSubdomain maps to the real public subdomain and can be null."
        ),
        tags=["Stores"],
        responses={200: StoreSettingsSerializer, **DOC_ERROR_RESPONSES},
    ),
    put=extend_schema(
        summary="Update store settings",
        description="Replace settings for a tenant-owned store.",
        tags=["Stores"],
        request=StoreSettingsUpdateRequestSerializer,
        responses={200: StoreSettingsSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update store settings",
        description="Partially update settings for a tenant-owned store.",
        tags=["Stores"],
        request=StoreSettingsUpdateRequestSerializer,
        responses={200: StoreSettingsSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class RetrieveUpdateStoreSettingsView(StoreAccessMixin, generics.GenericAPIView):
    """
    Get or update StoreSettings for a specific store.
    GET /api/stores/{store_id}/settings/
    PATCH /api/stores/{store_id}/settings/
    """
    serializer_class = StoreSettingsSerializer
    permission_classes = [TenantAuthenticated]

    def _get_store_with_access_check(self):
        store_id = self.kwargs['store_id']
        store = self._get_store_or_not_found(store_id)
        self._enforce_store_access(self.request, store)
        return store

    def _get_or_create_store_settings(self, store):
        settings_obj, _created = StoreSettings.objects.get_or_create(store=store)
        return settings_obj

    def get(self, request, *args, **kwargs):
        store = self._get_store_with_access_check()
        settings_obj = self._get_or_create_store_settings(store)
        serializer = self.get_serializer(settings_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        store = self._get_store_with_access_check()
        self._get_or_create_store_settings(store)

        request_serializer = StoreSettingsUpdateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        settings_payload = request_serializer.validated_data["settings"]

        serializer = StoreSettingsUpdateSerializer(data=settings_payload, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_settings = update_store_settings(
                store=store,
                user=request.user,
                **serializer.validated_data
            )
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = self.get_serializer(updated_settings)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        kwargs['partial'] = False
        return self.update(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


# StoreDomain Views
@extend_schema_view(
    get=extend_schema(
        summary="List store domains",
        description="List domains configured for a tenant-owned store.",
        tags=["Stores"],
        responses={200: StoreDomainSerializer(many=True), **DOC_ERROR_RESPONSES},
    ),
    post=extend_schema(
        summary="Create store domain",
        description=(
            "Create a new domain for a tenant-owned store. If is_primary is true, existing primary "
            "domains for the store are unset. Duplicate domain values fail because domains are globally unique."
        ),
        tags=["Stores"],
        request=StoreDomainSerializer,
        responses={201: StoreDomainSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class ListCreateStoreDomainView(StoreAccessMixin, generics.ListCreateAPIView):
    """
    List all domains for a store or create a new one.
    GET /api/stores/{store_id}/domains/
    POST /api/stores/{store_id}/domains/
    """
    serializer_class = StoreDomainSerializer
    permission_classes = [TenantAuthenticated]
    
    def get_queryset(self):
        store_id = self.kwargs['store_id']
        store = get_store_by_id(store_id, tenant_id=getattr(self.request, 'tenant_id', None))
        if not store:
            return StoreDomain.objects.none()
        if not self._has_store_access(self.request, store):
            return StoreDomain.objects.none()
        return get_store_domains_by_store_id(store_id)
    
    def perform_create(self, serializer):
        store_id = self.kwargs['store_id']
        store = self._get_store_or_not_found(store_id)
        self._enforce_store_access(self.request, store)
        
        domain = serializer.validated_data['domain']
        is_primary = serializer.validated_data.get('is_primary', False)
        
        domain_obj = add_domain(store, domain, is_primary)
        serializer.instance = domain_obj


@extend_schema_view(
    get=extend_schema(
        summary="Get store domain",
        description="Retrieve a single domain for a tenant-owned store.",
        tags=["Stores"],
        responses={200: StoreDomainSerializer, **DOC_ERROR_RESPONSES},
    ),
    put=extend_schema(
        summary="Update store domain",
        description=(
            "Replace a domain configuration for a tenant-owned store. If is_primary is true, existing "
            "primary domains for the store are unset."
        ),
        tags=["Stores"],
        request=StoreDomainSerializer,
        responses={200: StoreDomainSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update store domain",
        description=(
            "Partially update a domain configuration for a tenant-owned store. If is_primary is true, "
            "existing primary domains for the store are unset."
        ),
        tags=["Stores"],
        request=StoreDomainSerializer,
        responses={200: StoreDomainSerializer, **DOC_ERROR_RESPONSES},
    ),
    delete=extend_schema(
        summary="Delete store domain",
        description="Delete a domain from a tenant-owned store.",
        tags=["Stores"],
        responses={
            204: OpenApiResponse(description="Store domain deleted successfully."),
            **DOC_ERROR_RESPONSES,
        },
    ),
)
class RetrieveUpdateDestroyStoreDomainView(StoreAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a specific domain.
    GET /api/stores/{store_id}/domains/{domain_id}/
    PATCH /api/stores/{store_id}/domains/{domain_id}/
    DELETE /api/stores/{store_id}/domains/{domain_id}/
    """
    serializer_class = StoreDomainSerializer
    permission_classes = [TenantAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = 'domain_id'
    
    def get_queryset(self):
        store_id = self.kwargs['store_id']
        store = get_store_by_id(store_id, tenant_id=getattr(self.request, 'tenant_id', None))
        if not store:
            return StoreDomain.objects.none()
        if not self._has_store_access(self.request, store):
            return StoreDomain.objects.none()
        return get_store_domains_by_store_id(store_id)
    
    def perform_update(self, serializer):
        store_id = self.kwargs['store_id']
        store = self._get_store_or_not_found(store_id)
        self._enforce_store_access(self.request, store)
        domain_obj = self.get_object()

        new_domain = serializer.validated_data.get('domain', domain_obj.domain)
        is_primary = serializer.validated_data.get('is_primary', domain_obj.is_primary)

        # Use service to update (handles primary domain logic)
        updated_domain = update_domain(
            store,
            domain_obj.domain,
            is_primary,
            new_domain=new_domain,
        )
        serializer.instance = updated_domain
    
    def perform_destroy(self, instance):
        store_id = self.kwargs['store_id']
        store = self._get_store_or_not_found(store_id)
        self._enforce_store_access(self.request, store)
        delete_domain(store, instance.domain)

