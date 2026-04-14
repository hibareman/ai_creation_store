import logging
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from .models import Store, StoreSettings, StoreDomain
from .serializers import (
    StoreSerializer,
    StoreSettingsSerializer,
    StoreDomainSerializer,
    CheckSlugSerializer,
    SuggestSlugSerializer,
)
from .services import (
    create_store,
    update_store_settings,
    add_domain,
    update_domain,
    delete_domain,
    is_slug_available,
    suggest_slugs,
)
from .selectors import get_user_stores, get_store_by_id, get_store_domains_by_store_id
from users.permissions import TenantAuthenticated

logger = logging.getLogger(__name__)


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

# Delete store
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


# StoreSettings Views
class RetrieveUpdateStoreSettingsView(StoreAccessMixin, generics.RetrieveUpdateAPIView):
    """
    Get or update StoreSettings for a specific store.
    GET /api/stores/{store_id}/settings/
    PATCH /api/stores/{store_id}/settings/
    """
    serializer_class = StoreSettingsSerializer
    permission_classes = [TenantAuthenticated]
    
    def get_object(self):
        store_id = self.kwargs['store_id']
        store = self._get_store_or_not_found(store_id)
        self._enforce_store_access(self.request, store)
        return store.settings
    
    # ًں”´ ط£ط¶ظپ ظ‡ط°ظ‡ ط§ظ„ط¯ط§ظ„ط© ظ„طھط­ط¯ظٹط« ط§ظ„ط¥ط¹ط¯ط§ط¯ط§طھ ظ…ط¹ ط§ظ„طھط­ظ‚ظ‚
    def update(self, request, *args, **kwargs):
        """Update store settings with permission check"""
        partial = kwargs.pop('partial', False)
        store_id = self.kwargs['store_id']
        store = self._get_store_or_not_found(store_id)
        self._enforce_store_access(request, store)

        serializer = self.get_serializer(store.settings, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            updated_settings = update_store_settings(
                store=store,
                user=request.user,
                **serializer.validated_data
            )
            serializer = self.get_serializer(updated_settings)
            return Response(serializer.data)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    # ًں”´ ط£ط¶ظپ ظ‡ط°ظ‡ ط§ظ„ط¯ط§ظ„ط© ظ„ظ„ظ€ PATCH
    def patch(self, request, *args, **kwargs):
        """Partial update of store settings"""
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


# StoreDomain Views
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
        store = get_store_by_id(store_id)
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
        store = get_store_by_id(store_id)
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
        
        is_primary = serializer.validated_data.get('is_primary', domain_obj.is_primary)
        
        # Use service to update (handles primary domain logic)
        updated_domain = update_domain(store, domain_obj.domain, is_primary)
        serializer.instance = updated_domain
    
    def perform_destroy(self, instance):
        store_id = self.kwargs['store_id']
        store = self._get_store_or_not_found(store_id)
        self._enforce_store_access(self.request, store)
        delete_domain(store, instance.domain)

