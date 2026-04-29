from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import CharField, Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Concat
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order
from platform_admin.models import get_platform_admin_settings
from products.models import Product
from stores.models import Store
from users.permissions import IsSuperAdmin

from .serializers import (
    ADMIN_STATUS_CHOICES,
    AdminDashboardResponseSerializer,
    AdminPlatformSettingsResponseSerializer,
    AdminPlatformSettingsUpdateRequestSerializer,
    AdminStoresListResponseSerializer,
    AdminUserSummarySerializer,
    AdminUsersListResponseSerializer,
    StoreAdminSummarySerializer,
    StoreStatusUpdateResponseSerializer,
    StoreStatusUpdateSerializer,
    decimal_to_json_number,
    map_admin_status_to_backend,
    map_backend_status_to_admin,
)


def get_admin_store_queryset():
    products_count = (
        Product.objects.filter(store=OuterRef("pk"))
        .values("store")
        .annotate(total=Count("id"))
        .values("total")[:1]
    )
    orders_count = (
        Order.objects.filter(store=OuterRef("pk"))
        .values("store")
        .annotate(total=Count("id"))
        .values("total")[:1]
    )
    revenue_total = (
        Order.objects.filter(store=OuterRef("pk"))
        .values("store")
        .annotate(total=Sum("total_price"))
        .values("total")[:1]
    )

    return Store.objects.select_related("owner").annotate(
        products_count=Coalesce(
            Subquery(products_count, output_field=IntegerField()),
            Value(0),
        ),
        orders_count=Coalesce(
            Subquery(orders_count, output_field=IntegerField()),
            Value(0),
        ),
        revenue_total=Coalesce(
            Subquery(
                revenue_total,
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )


def get_store_status_counts():
    counts = {"active": 0, "pending": 0, "suspended": 0}
    for row in Store.objects.values("status").annotate(total=Count("id")):
        admin_status = map_backend_status_to_admin(row["status"])
        counts[admin_status] += row["total"]
    return counts


def backend_statuses_for_admin_status(admin_status):
    if admin_status == "active":
        return ["active"]
    if admin_status == "pending":
        return ["setup", "draft"]
    if admin_status == "suspended":
        return ["inactive"]
    return []


def get_admin_user_queryset():
    User = get_user_model()
    return User.objects.annotate(stores_count=Count("stores", distinct=True))


class SuperAdminAPIView(APIView):
    permission_classes = [IsSuperAdmin]
    renderer_classes = [JSONRenderer]


class AdminDashboardView(SuperAdminAPIView):

    @extend_schema(
        tags=["Super Admin"],
        summary="Get Super Admin dashboard metrics",
        responses={
            200: AdminDashboardResponseSerializer,
            401: OpenApiResponse(description="Authentication credentials were not provided or invalid."),
            403: OpenApiResponse(description="User is not a Super Admin."),
        },
    )
    def get(self, request):
        User = get_user_model()
        platform_revenue = Order.objects.aggregate(total=Sum("total_price"))["total"]
        recent_stores = get_admin_store_queryset().order_by("-created_at", "-id")[:5]

        payload = {
            "stats": {
                "total_stores": Store.objects.count(),
                "active_users": User.objects.filter(is_active=True).count(),
                "total_orders": Order.objects.count(),
                "platform_revenue": decimal_to_json_number(platform_revenue),
            },
            "store_status": get_store_status_counts(),
            "recent_stores": StoreAdminSummarySerializer(recent_stores, many=True).data,
        }
        return Response(payload, status=status.HTTP_200_OK)


class AdminStoresListView(SuperAdminAPIView):

    @extend_schema(
        tags=["Super Admin"],
        summary="List stores for Super Admin management",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                required=False,
                description="Case-insensitive search by store name or owner identity fields.",
            ),
            OpenApiParameter(
                name="status",
                type=str,
                required=False,
                enum=list(ADMIN_STATUS_CHOICES),
                description="Filter by admin status: active, pending, or suspended.",
            ),
        ],
        responses={
            200: AdminStoresListResponseSerializer,
            400: OpenApiResponse(description="Invalid status filter."),
            401: OpenApiResponse(description="Authentication credentials were not provided or invalid."),
            403: OpenApiResponse(description="User is not a Super Admin."),
        },
    )
    def get(self, request):
        queryset = get_admin_store_queryset().order_by("-created_at", "-id")
        search = request.query_params.get("search", "").strip()
        admin_status = request.query_params.get("status", "").strip()

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(owner__username__icontains=search)
                | Q(owner__email__icontains=search)
                | Q(owner__first_name__icontains=search)
                | Q(owner__last_name__icontains=search)
            )

        if admin_status:
            if admin_status not in ADMIN_STATUS_CHOICES:
                return Response(
                    {"detail": "Invalid status filter."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status__in=backend_statuses_for_admin_status(admin_status))

        return Response(
            {"items": StoreAdminSummarySerializer(queryset, many=True).data},
            status=status.HTTP_200_OK,
        )


class AdminUsersListView(SuperAdminAPIView):

    @extend_schema(
        tags=["Super Admin"],
        summary="List users for Super Admin management",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                required=False,
                description="Case-insensitive search by username, email, first name, last name, or full name.",
            ),
        ],
        responses={
            200: AdminUsersListResponseSerializer,
            401: OpenApiResponse(description="Authentication credentials were not provided or invalid."),
            403: OpenApiResponse(description="User is not a Super Admin."),
        },
    )
    def get(self, request):
        queryset = get_admin_user_queryset().order_by("-created_at", "-id")
        search = request.query_params.get("search", "").strip()

        if search:
            queryset = queryset.annotate(
                full_name_search=Concat(
                    "first_name",
                    Value(" "),
                    "last_name",
                    output_field=CharField(),
                )
            ).filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(full_name_search__icontains=search)
            )

        return Response(
            {"items": AdminUserSummarySerializer(queryset, many=True).data},
            status=status.HTTP_200_OK,
        )


class AdminPlatformSettingsView(SuperAdminAPIView):

    @extend_schema(
        tags=["Super Admin"],
        summary="Get Super Admin platform settings",
        responses={
            200: AdminPlatformSettingsResponseSerializer,
            401: OpenApiResponse(description="Authentication credentials were not provided or invalid."),
            403: OpenApiResponse(description="User is not a Super Admin."),
        },
    )
    def get(self, request):
        settings_obj = get_platform_admin_settings()
        return Response(
            {"settings": AdminPlatformSettingsResponseSerializer({"settings": settings_obj}).data["settings"]},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Super Admin"],
        summary="Update Super Admin platform settings",
        request=AdminPlatformSettingsUpdateRequestSerializer,
        responses={
            200: AdminPlatformSettingsResponseSerializer,
            400: OpenApiResponse(description="Invalid platform settings payload."),
            401: OpenApiResponse(description="Authentication credentials were not provided or invalid."),
            403: OpenApiResponse(description="User is not a Super Admin."),
        },
    )
    def patch(self, request):
        request_serializer = AdminPlatformSettingsUpdateRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(
                {"detail": request_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        settings_obj = get_platform_admin_settings()
        settings_payload = request_serializer.validated_data["settings"]
        update_fields = []
        for field, value in settings_payload.items():
            setattr(settings_obj, field, value)
            update_fields.append(field)

        if update_fields:
            settings_obj.save(update_fields=[*update_fields, "updated_at"])

        return Response(
            {"settings": AdminPlatformSettingsResponseSerializer({"settings": settings_obj}).data["settings"]},
            status=status.HTTP_200_OK,
        )


class AdminStoreStatusView(SuperAdminAPIView):

    @extend_schema(
        tags=["Super Admin"],
        summary="Update a store admin status",
        request=StoreStatusUpdateSerializer,
        responses={
            200: StoreStatusUpdateResponseSerializer,
            400: OpenApiResponse(description="Invalid status value."),
            401: OpenApiResponse(description="Authentication credentials were not provided or invalid."),
            403: OpenApiResponse(description="User is not a Super Admin."),
            404: OpenApiResponse(description="Store not found."),
        },
    )
    def patch(self, request, store_id):
        serializer = StoreStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Invalid status value."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        store = get_object_or_404(Store, pk=store_id)
        store.status = map_admin_status_to_backend(serializer.validated_data["status"])
        store.save(update_fields=["status", "updated_at"])
        annotated_store = get_admin_store_queryset().get(pk=store.pk)

        return Response(
            {"store": StoreAdminSummarySerializer(annotated_store).data},
            status=status.HTTP_200_OK,
        )
