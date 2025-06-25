import pytest
import io
import csv
from rest_framework.test import APIClient
from accounts.models import Tenant
from chat.models import PromptLog, Conversation
from unittest.mock import patch


@pytest.mark.django_db
def test_export_prompt_logs_csv(api_client, user, tenant, subscribtion):
    user.tenant = tenant
    user.save()
    api_client.force_authenticate(user=user)
    conversation = Conversation.objects.create(
        tenant=tenant,
        user_identifier="test-user"
    )

    conv = Conversation.objects.create(id=100, tenant=tenant)
    PromptLog.objects.create(
        tenant=tenant,
        conversation=conv,
        prompt="Co to jest AI?",
        response="Sztuczna inteligencja",
        tokens=10,
        source="faq",
        model="gpt-3.5-turbo"
    )

    headers = {"HTTP_X_API_KEY": tenant.api_key}
    res = api_client.get("/api/chat/export/", **headers)

    assert res.status_code == 200
    assert res["Content-Type"] == "text/csv"
    content = res.content.decode("utf-8")
    assert "prompt,response" in content or "Co to jest AI?" in content


@pytest.mark.django_db
def test_import_prompt_logs_csv(api_client, user, tenant, subscribtion):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    api_client.force_authenticate(user=user)

    csv_content = "prompt,response\nCzym jest Python?,Język programowania\n"
    file = io.BytesIO(csv_content.encode("utf-8"))
    file.name = "prompts.csv"

    response = api_client.post(
        "/api/chat/import/",
        {"file": file},
        format="multipart",
        HTTP_X_API_KEY=str(tenant.api_key)
    )

    assert response.status_code == 201
    assert response.data["imported"] == 1


@pytest.mark.django_db
def test_import_prompt_logs_missing_file(api_client, user, tenant, subscribtion):
    user.tenant = tenant
    user.role = "owner"
    user.save()
    api_client.force_authenticate(user=user)

    response = api_client.post(
        "/api/chat/import/",
        {},
        format="multipart",
        HTTP_X_API_KEY=str(tenant.api_key)
    )

    assert response.status_code == 400
    assert response.data["error"] == "Brak pliku CSV."
