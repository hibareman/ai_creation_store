from django.urls import path
from .views import (
    StoreListCreateView, UpdateStoreView, DestroyStoreView,
    RetrieveUpdateStoreSettingsView,
    ListCreateStoreDomainView, RetrieveUpdateDestroyStoreDomainView,
    CheckSlugAvailabilityView, SuggestSlugView,
    PublicStoreDetailView,
    SetStoreSubdomainView,
    StorePublishActionView,
)

urlpatterns = [
    # Store endpoints
    path('', StoreListCreateView.as_view(), name='store-list-create'),
    path('<int:id>/', UpdateStoreView.as_view(), name='update-store'),
    path('<int:id>/delete/', DestroyStoreView.as_view(), name='delete-store'),
    
    # StoreSettings endpoints
    path('<int:store_id>/settings/', RetrieveUpdateStoreSettingsView.as_view(), name='store-settings'),
    
    # Slug helper endpoints
    path('slug/check/', CheckSlugAvailabilityView.as_view(), name='check-slug'),
    path('slug/suggest/', SuggestSlugView.as_view(), name='suggest-slug'),
    path('public/store/<slug:subdomain>/', PublicStoreDetailView.as_view(), name='public-store-detail'),
    path('<int:store_id>/subdomain/', SetStoreSubdomainView.as_view(), name='set-store-subdomain'),
    path('<int:store_id>/publish/', StorePublishActionView.as_view(), name='store-publish-action'),

    # StoreDomain endpoints
    path('<int:store_id>/domains/', ListCreateStoreDomainView.as_view(), name='storedomain-list-create'),
    path('<int:store_id>/domains/<int:domain_id>/', RetrieveUpdateDestroyStoreDomainView.as_view(), name='storedomain-detail'),
]
