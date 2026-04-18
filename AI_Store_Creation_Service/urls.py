from django.urls import path

from .views import (
    AIApplyDraftAPIView,
    AIClarificationAPIView,
    AICurrentDraftAPIView,
    AIRegenerateDraftAPIView,
    AIRegenerateSectionAPIView,
    AIStartDraftAPIView,
)


app_name = "ai_store_creation"


urlpatterns = [
    path(
        "stores/draft/start/",
        AIStartDraftAPIView.as_view(),
        name="start-draft",
    ),
    path(
        "stores/<int:store_id>/draft/",
        AICurrentDraftAPIView.as_view(),
        name="current-draft",
    ),
    path(
        "stores/<int:store_id>/draft/clarify/",
        AIClarificationAPIView.as_view(),
        name="clarify-draft",
    ),
    path(
        "stores/<int:store_id>/draft/regenerate/",
        AIRegenerateDraftAPIView.as_view(),
        name="regenerate-draft",
    ),
    path(
        "stores/<int:store_id>/draft/regenerate-section/",
        AIRegenerateSectionAPIView.as_view(),
        name="regenerate-draft-section",
    ),
    path(
        "stores/<int:store_id>/draft/apply/",
        AIApplyDraftAPIView.as_view(),
        name="apply-draft",
    ),
]
