from django.urls import path

from .views import ThemeTemplateListView, StoreThemeConfigDetailView


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
]
