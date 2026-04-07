from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from .models import Store, StoreSettings, StoreDomain
from .serializers import StoreSerializer, StoreSettingsSerializer, StoreDomainSerializer
from .services import create_store, update_store_settings, add_domain, update_domain, delete_domain
from users.permissions import TenantAuthenticated

# Create store
class StoreListCreateView(generics.ListCreateAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == 'Super Admin':
            return Store.objects.all()
        return Store.objects.filter(tenant_id=self.request.tenant_id)

    def perform_create(self, serializer):
        owner = self.request.user
        store = create_store(
            owner=owner,
            name=serializer.validated_data['name'],
            description=serializer.validated_data.get('description', ''),
            status=serializer.validated_data.get('status', 'active')
        )
        serializer.instance = store

# Update store
class UpdateStoreView(generics.UpdateAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, TenantAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        if self.request.user.role == 'Super Admin':
            return Store.objects.all()
        return Store.objects.filter(tenant_id=self.request.tenant_id)

# Delete store
class DestroyStoreView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, TenantAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        if self.request.user.role == 'Super Admin':
            return Store.objects.all()
        return Store.objects.filter(tenant_id=self.request.tenant_id)


# StoreSettings Views
class RetrieveUpdateStoreSettingsView(generics.RetrieveUpdateAPIView):
    """
    Get or update StoreSettings for a specific store.
    GET /api/stores/{store_id}/settings/
    PATCH /api/stores/{store_id}/settings/
    """
    serializer_class = StoreSettingsSerializer
    permission_classes = [IsAuthenticated]
    
    def get_object(self):
        store_id = self.kwargs['store_id']
        try:
            store = Store.objects.get(id=store_id)
        except Store.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Store not found")
        
        # Check ownership - user must own the store or be Super Admin
        if self.request.user.role != 'Super Admin' and store.owner_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to access this store's settings")
        
        return store.settings


# StoreDomain Views
class ListCreateStoreDomainView(generics.ListCreateAPIView):
    """
    List all domains for a store or create a new one.
    GET /api/stores/{store_id}/domains/
    POST /api/stores/{store_id}/domains/
    """
    serializer_class = StoreDomainSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        store_id = self.kwargs['store_id']
        try:
            store = Store.objects.get(id=store_id)
        except Store.DoesNotExist:
            return StoreDomain.objects.none()
        
        # Check ownership
        if self.request.user.role != 'Super Admin' and store.owner_id != self.request.user.id:
            return StoreDomain.objects.none()
        
        return StoreDomain.objects.filter(store_id=store_id)
    
    def perform_create(self, serializer):
        store_id = self.kwargs['store_id']
        store = Store.objects.get(id=store_id)
        
        # Check ownership
        if self.request.user.role != 'Super Admin' and store.owner_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to add domains to this store")
        
        domain = serializer.validated_data['domain']
        is_primary = serializer.validated_data.get('is_primary', False)
        
        domain_obj = add_domain(store, domain, is_primary)
        serializer.instance = domain_obj


class RetrieveUpdateDestroyStoreDomainView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a specific domain.
    GET /api/stores/{store_id}/domains/{domain_id}/
    PATCH /api/stores/{store_id}/domains/{domain_id}/
    DELETE /api/stores/{store_id}/domains/{domain_id}/
    """
    serializer_class = StoreDomainSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = 'domain_id'
    
    def get_queryset(self):
        store_id = self.kwargs['store_id']
        try:
            store = Store.objects.get(id=store_id)
        except Store.DoesNotExist:
            return StoreDomain.objects.none()
        
        # Check ownership
        if self.request.user.role != 'Super Admin' and store.owner_id != self.request.user.id:
            return StoreDomain.objects.none()
        
        return StoreDomain.objects.filter(store_id=store_id)
    
    def perform_update(self, serializer):
        store_id = self.kwargs['store_id']
        store = Store.objects.get(id=store_id)
        domain_obj = self.get_object()
        
        is_primary = serializer.validated_data.get('is_primary', domain_obj.is_primary)
        
        # Use service to update (handles primary domain logic)
        updated_domain = update_domain(store, domain_obj.domain, is_primary)
        serializer.instance = updated_domain
    
    def perform_destroy(self, instance):
        store_id = self.kwargs['store_id']
        store = Store.objects.get(id=store_id)
        delete_domain(store, instance.domain)