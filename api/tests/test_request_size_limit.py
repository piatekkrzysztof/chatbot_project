"""Limit Django musi działać również przy parsowaniu request.data przez DRF."""

import json
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import CustomUser, Subscription
from chat.models import FAQ


@pytest.mark.django_db
@pytest.mark.parametrize("content_type", ["application/json", "application/x-www-form-urlencoded"])
@pytest.mark.parametrize("oversized", [False, True])
def test_faq_input_respects_django_body_limit(tenant, settings, content_type, oversized):
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 1024
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=30),
    )
    owner = CustomUser.objects.create_user(username="body-limit-owner", tenant=tenant, role="owner")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(owner)}")
    data = {"question": "Q" * (2048 if oversized else 20), "answer": "Synthetic answer"}
    payload = json.dumps(data) if content_type == "application/json" else urlencode(data)

    response = client.post(reverse("faq-list"), payload, content_type=content_type)

    assert response.status_code == (400 if oversized else 201)
    assert FAQ.objects.filter(tenant=tenant).count() == (0 if oversized else 1)
