from django.core.exceptions import ValidationError
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view

from stores.selectors import get_store_by_id
from users.permissions import TenantAuthenticated

from . import selectors, services
from .serializers import (
    AppearanceUpdateRequestSerializer,
    ThemeTemplateSerializer,
    StoreLogoUploadRequestSerializer,
    StoreLogoUploadResponseSerializer,
    StoreAppearanceSerializer,
    StoreThemeConfigSerializer,
    StoreThemeConfigUpdateSerializer,
)

DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Bad request"),
    403: OpenApiResponse(description="Permission denied"),
    404: OpenApiResponse(description="Not found"),
}


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


@extend_schema_view(
    get=extend_schema(
        summary="List active theme templates",
        description="List active theme templates available for a tenant-owned store.",
        tags=["Themes"],
        responses={200: ThemeTemplateSerializer(many=True), **DOC_ERROR_RESPONSES},
    ),
)
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


@extend_schema_view(
    get=extend_schema(
        summary="Get store theme configuration",
        description="Retrieve theme configuration for a tenant-owned store.",
        tags=["Themes"],
        responses={200: StoreThemeConfigSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Update store theme configuration",
        description="Create or update theme configuration for a tenant-owned store.",
        tags=["Themes"],
        request=StoreThemeConfigUpdateSerializer,
        responses={200: StoreThemeConfigSerializer, **DOC_ERROR_RESPONSES},
    ),
)
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

        theme_config = services.get_store_theme_config_for_read(store)

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


@extend_schema_view(
    get=extend_schema(
        summary="Get store appearance",
        description="Retrieve appearance/branding configuration for a tenant-owned store.",
        tags=["Themes"],
        responses={200: StoreAppearanceSerializer, **DOC_ERROR_RESPONSES},
    ),
    put=extend_schema(
        summary="Update store appearance",
        description="Replace appearance/branding configuration for a tenant-owned store.",
        tags=["Themes"],
        request=AppearanceUpdateRequestSerializer,
        responses={200: StoreAppearanceSerializer, **DOC_ERROR_RESPONSES},
    ),
    patch=extend_schema(
        summary="Partially update store appearance",
        description="Partially update appearance/branding configuration for a tenant-owned store.",
        tags=["Themes"],
        request=AppearanceUpdateRequestSerializer,
        responses={200: StoreAppearanceSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreAppearanceDetailView(ThemeStoreAccessMixin, generics.GenericAPIView):
    """
    GET /api/stores/{store_id}/appearance/
    PUT/PATCH /api/stores/{store_id}/appearance/
    """

    permission_classes = [TenantAuthenticated]

    def get_serializer_class(self):
        if self.request.method in {"PUT", "PATCH"}:
            return AppearanceUpdateRequestSerializer
        return StoreAppearanceSerializer

    def get(self, request, *args, **kwargs):
        store = self._get_store_or_not_found(self.kwargs["store_id"])
        self._enforce_store_access(request, store)

        theme_config = services.get_store_appearance_config_for_read(store)

        serializer = StoreAppearanceSerializer(theme_config)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _update(self, request):
        store = self._get_store_or_not_found(self.kwargs["store_id"])
        self._enforce_store_access(request, store)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data["appearance"]

        try:
            updated_config = services.update_store_appearance(
                user=request.user,
                store=store,
                primary_color=data.get("primaryColor"),
                background_color=data.get("backgroundColor"),
                font=data.get("font"),
                style=data.get("style"),
                logo_url=data.get("logoUrl"),
            )
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = StoreAppearanceSerializer(updated_config)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        return self._update(request)

    def patch(self, request, *args, **kwargs):
        return self._update(request)


@extend_schema_view(
    post=extend_schema(
        summary="Upload store logo asset",
        description="Upload a logo image for a tenant-owned store and update appearance logo URL.",
        tags=["Themes"],
        request=StoreLogoUploadRequestSerializer,
        responses={201: StoreLogoUploadResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class StoreLogoUploadView(ThemeStoreAccessMixin, generics.GenericAPIView):
    """
    POST /api/stores/{store_id}/assets/logo/
    """

    permission_classes = [TenantAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = StoreLogoUploadRequestSerializer

    def post(self, request, *args, **kwargs):
        store = self._get_store_or_not_found(self.kwargs["store_id"])
        self._enforce_store_access(request, store)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payload = services.upload_store_logo_asset(
                user=request.user,
                store=store,
                file_obj=serializer.validated_data["file"],
                alt=serializer.validated_data.get("alt", ""),
                absolute_url_builder=request.build_absolute_uri,
            )
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = StoreLogoUploadResponseSerializer(payload)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
