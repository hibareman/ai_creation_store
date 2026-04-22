from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

urlpatterns = [

    path('admin/', admin.site.urls),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('api/auth/', include('users.urls')),
    path('api/stores/', include('stores.urls')),
    path('api/', include('orders.urls')),
    # Category contract route used by tests/docs:
    # /api/stores/<store_id>/categories/
    path('api/', include('categories.urls')),
    # Backward-compatible route kept temporarily:
    path('api/categories/', include('categories.urls')),
    path('api/products/', include('products.urls')),
    path('api/', include('themes.urls')),
    path(
        'api/ai/',
        include(('AI_Store_Creation_Service.urls', 'ai_store_creation'), namespace='ai_store_creation'),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
