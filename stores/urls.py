from django.urls import path
from .views import (
    StoreListCreateView, UpdateStoreView, DestroyStoreView,
    RetrieveUpdateStoreSettingsView,
    ListCreateStoreDomainView, RetrieveUpdateDestroyStoreDomainView
)

urlpatterns = [
    # Store endpoints
    path('', StoreListCreateView.as_view(), name='store-list-create'),
    path('<int:id>/', UpdateStoreView.as_view(), name='update-store'),
    path('<int:id>/delete/', DestroyStoreView.as_view(), name='delete-store'),
    
    # StoreSettings endpoints
    path('<int:store_id>/settings/', RetrieveUpdateStoreSettingsView.as_view(), name='storesettings-detail'),
    
    # StoreDomain endpoints
    path('<int:store_id>/domains/', ListCreateStoreDomainView.as_view(), name='storedomain-list-create'),
    path('<int:store_id>/domains/<int:domain_id>/', RetrieveUpdateDestroyStoreDomainView.as_view(), name='storedomain-detail'),
]