from django.urls import path

from .views import (
    ThemeTemplateListView,
    StoreThemeConfigDetailView,
    StoreAppearanceDetailView,
    StoreLogoUploadView,
)


urlpatterns = [
    path(
        "stores/<int:store_id>/themes/templates/",
        ThemeTemplateListView.as_view(),
        name="theme-template-list",
    ),
    path(
        "stores/<int:store_id>/theme/",
        StoreThemeConfigDetailView.as_view(),
        name="store-theme-config-detail",
    ),
    path(
        "stores/<int:store_id>/appearance/",
        StoreAppearanceDetailView.as_view(),
        name="store-appearance",
    ),
    path(
        "stores/<int:store_id>/assets/logo/",
        StoreLogoUploadView.as_view(),
        name="store-logo-upload",
    ),
]
