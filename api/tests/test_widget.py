import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
import uuid


@pytest.mark.django_db
def test_widget_settings_success():
    client = APIClient()
    api_key = uuid.uuid4()
    tenant = Tenant.objects.create(
        name="Testowa Firma",
        api_key=api_key,
        widget_position="right",
        widget_color="#00ff00",
        widget_title="Zapytaj nas!",
        owner_email="owner@example.com"
    )

    response = client.get("/api/widget/settings/", HTTP_X_API_KEY=str(api_key))

    assert response.status_code == 200
    assert response.json() == {
        "widget_position": "right",
        "widget_color": "#00ff00",
        "widget_title": "Zapytaj nas!"
    }


@pytest.mark.django_db
def test_widget_settings_invalid_key():
    client = APIClient()
    response = client.get("/api/widget/settings/", HTTP_X_API_KEY=str(uuid.uuid4()))
    assert response.status_code == 403
    assert response.json()["error"] == "Niepoprawny klucz API"


@pytest.mark.django_db
def test_widget_settings_missing_key():
    client = APIClient()
    response = client.get("/api/widget/settings/")
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.django_db
def test_widget_settings_invalid_uuid_format():
    client = APIClient()
    response = client.get("/api/widget/settings/", HTTP_X_API_KEY="not-a-uuid")
    assert response.status_code == 400
    assert "format" in response.json()["error"]
