from django.urls import path

from .views import (
    AdminDashboardView,
    AdminPlatformSettingsView,
    AdminStoresListView,
    AdminStoreStatusView,
    AdminUsersListView,
)

urlpatterns = [
    path("dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path("settings/", AdminPlatformSettingsView.as_view(), name="admin-settings"),
    path("stores/", AdminStoresListView.as_view(), name="admin-stores"),
    path("stores/<int:store_id>/status/", AdminStoreStatusView.as_view(), name="admin-store-status"),
    path("users/", AdminUsersListView.as_view(), name="admin-users"),
]
