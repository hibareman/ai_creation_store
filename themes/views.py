from django.core.exceptions import ValidationError
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied

from stores.selectors import get_store_by_id
from users.permissions import TenantAuthenticated

from . import selectors, services
from .serializers import (
    ThemeTemplateSerializer,
    StoreThemeConfigSerializer,
    StoreThemeConfigUpdateSerializer,
)


class ThemeStoreAccessMixin:
    """
    Minimal shared helpers for trusted store-scoped theme access.
    """

    def _get_store_or_not_found(self, store_id):
        store = get_store_by_id(store_id)
        if not store:
            raise NotFound("Store not found")
        return store

    def _enforce_store_access(self, request, store):
        if getattr(request, "tenant_id", None) != store.tenant_id:
            raise PermissionDenied("You do not have access to this store")
        if request.user.id != store.owner_id:
            raise PermissionDenied("You do not own this store")


class ThemeTemplateListView(ThemeStoreAccessMixin, generics.ListAPIView):
    """
    GET /api/stores/{store_id}/themes/templates/
    """

    serializer_class = ThemeTemplateSerializer
    permission_classes = [TenantAuthenticated]

    def get_queryset(self):
        store = self._get_store_or_not_found(self.kwargs["store_id"])
        self._enforce_store_access(self.request, store)
        return selectors.get_active_theme_templates()


class StoreThemeConfigDetailView(ThemeStoreAccessMixin, generics.GenericAPIView):
    """
    GET /api/stores/{store_id}/theme/
    PATCH /api/stores/{store_id}/theme/
    """

    permission_classes = [TenantAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return StoreThemeConfigUpdateSerializer
        return StoreThemeConfigSerializer

    def get(self, request, *args, **kwargs):
        store = self._get_store_or_not_found(self.kwargs["store_id"])
        self._enforce_store_access(request, store)

        theme_config = selectors.get_store_theme_config(store)
        if not theme_config:
            raise NotFound("Store theme configuration not found")

        serializer = StoreThemeConfigSerializer(theme_config)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        store = self._get_store_or_not_found(self.kwargs["store_id"])
        self._enforce_store_access(request, store)

        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        theme_config = selectors.get_store_theme_config(store)

        try:
            if theme_config:
                updated_config = services.update_store_theme_config(
                    user=request.user,
                    store=store,
                    theme_template_id=(
                        data["theme_template"].id if "theme_template" in data else None
                    ),
                    primary_color=data.get("primary_color"),
                    secondary_color=data.get("secondary_color"),
                    font_family=data.get("font_family"),
                    logo_url=data.get("logo_url"),
                    banner_url=data.get("banner_url"),
                )
            else:
                required_fields = ["theme_template", "primary_color", "secondary_color", "font_family"]
                missing_fields = [field for field in required_fields if field not in data]
                if missing_fields:
                    return Response(
                        {
                            "detail": (
                                "Store theme configuration does not exist yet. "
                                f"Missing required fields for initial creation: {', '.join(missing_fields)}"
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                updated_config = services.get_or_create_store_theme_config(
                    user=request.user,
                    store=store,
                    theme_template_id=data["theme_template"].id,
                    primary_color=data["primary_color"],
                    secondary_color=data["secondary_color"],
                    font_family=data["font_family"],
                    logo_url=data.get("logo_url", ""),
                    banner_url=data.get("banner_url", ""),
                )
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = StoreThemeConfigSerializer(updated_config)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
