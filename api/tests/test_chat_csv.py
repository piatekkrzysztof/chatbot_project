import pytest
import io
import csv
from rest_framework.test import APIClient
from accounts.models import Tenant
from chat.models import PromptLog, Conversation


@pytest.mark.django_db
def test_export_prompt_logs_csv():
    client = APIClient()
    tenant = Tenant.objects.create(name="Firma",  owner_email="x@example.com")
    conv = Conversation.objects.create(id=100, tenant=tenant)

    PromptLog.objects.create(
        tenant=tenant, conversation=conv,
        prompt="Co to jest AI?", response="Sztuczna inteligencja",
        tokens=10, source="faq", model="gpt-3.5-turbo"
    )

    res = client.get("/api/chat/export/", HTTP_X_API_KEY=tenant.api_key)
    assert res.status_code == 200
    assert res["Content-Type"] == "text/csv"
    content = res.content.decode("utf-8")
    assert "prompt,response" in content or "Co to jest AI?" in content


@pytest.mark.django_db
def test_import_prompt_logs_csv():
    client = APIClient()
    tenant = Tenant.objects.create(name="Firma",  owner_email="x@example.com")

    csv_content = "prompt,response\nCzym jest Python?,Język programowania\n"
    file = io.BytesIO(csv_content.encode("utf-8"))
    file.name = "prompts.csv"

    res = client.post(
        "/api/chat/import/",
        {"file": file},
        format="multipart",
        HTTP_X_API_KEY=tenant.api_key
    )

    assert res.status_code == 201
    assert res.json()["imported"] == 1

    logs = PromptLog.objects.filter(tenant=tenant)
    assert logs.count() == 1
    assert logs.first().prompt == "Czym jest Python?"
    assert logs.first().source == "imported"


@pytest.mark.django_db
def test_import_prompt_logs_missing_file():
    client = APIClient()
    tenant = Tenant.objects.create(name="Firma", owner_email="x@example.com")

    res = client.post("/api/chat/import/", {}, HTTP_X_API_KEY=tenant.api_key)
    assert res.status_code == 400
    assert "Brak pliku CSV" in res.json()["error"]
