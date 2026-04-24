"""
Optional live-provider integration tests.

These tests are intentionally skipped by default and run only when explicitly
enabled with environment variables.
"""

from __future__ import annotations

import os
from unittest import skipUnless

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from themes.models import ThemeTemplate
from users.models import User


RUN_LIVE_AI_TESTS = os.getenv("RUN_LIVE_AI_TESTS") == "1"
HAS_AI_API_KEY = bool(os.getenv("AI_API_KEY", "").strip())


@skipUnless(
    RUN_LIVE_AI_TESTS and HAS_AI_API_KEY,
    "Live AI tests are disabled. Set RUN_LIVE_AI_TESTS=1 and AI_API_KEY to enable.",
)
class AILiveProviderIntegrationTests(TestCase):
    """
    End-to-end check for the AI start-draft flow using a real provider call.

    This verifies:
    - auth + endpoint wiring
    - provider connectivity
    - parser/validator pipeline produces a non-fallback draft
    """

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="live_ai_owner",
            email="live_ai_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
            tenant_id=8801,
        )
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])

        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Required by AI flow before provider call.
        ThemeTemplate.objects.create(
            name="Modern",
            description="Template for live provider integration tests.",
        )

    @staticmethod
    def _payload(response):
        return response.json()

    def test_start_draft_live_provider_returns_non_fallback(self):
        response = self.client.post(
            "/api/ai/stores/draft/start/",
            {
                "user_description": "A niche gadgets store for remote workers.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        envelope = self._payload(response)
        self.assertEqual(envelope.get("status"), "success")
        data = envelope.get("data") or {}
        metadata = data.get("draft_metadata") or {}

        self.assertIsInstance(data.get("store_id"), int)
        self.assertIsInstance(data.get("draft_payload"), dict)
        self.assertIn(metadata.get("status"), {"draft_ready", "needs_clarification"})
        self.assertFalse(
            metadata.get("is_fallback"),
            "Live provider returned fallback payload. Check AI_API_KEY/model/provider compatibility.",
        )
