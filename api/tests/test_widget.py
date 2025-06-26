import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
import uuid


@pytest.mark.django_db
def test_widget_settings_success(api_client, tenant, user, subscribtion, ):
    tenant.widget_position = "right",
    tenant.widget_color = "#00ff00",
    tenant.widget_title = "Zapytaj nas!"
    user.tenant = tenant
    user.role = "owner"
    user.save()
    api_client.force_authenticate(user=user)

    response = api_client.get("/api/widget-settings/", HTTP_X_API_KEY=str(tenant.api_key))

    assert response.status_code == 200
    assert response.json() == {
        "widget_position": "right",
        "widget_color": "#00ff00",
        "widget_title": "Zapytaj nas!"
    }


@pytest.mark.django_db
def test_widget_settings_invalid_key(api_client, tenant, user, subscribtion, ):
    client = APIClient()
    response = client.get("/api/widget/settings/", HTTP_X_API_KEY=str(uuid.uuid4()))
    assert response.status_code == 403
    assert response.json()["error"] == "Niepoprawny klucz API"


@pytest.mark.django_db
def test_widget_settings_missing_key(api_client, tenant, user, subscribtion, ):
    client = APIClient()
    response = client.get("/api/widget/settings/")
    assert response.status_code == 400
    assert "error" in response.json(api_client, tenant, user, subscribtion, )


@pytest.mark.django_db
def test_widget_settings_invalid_uuid_format(api_client, tenant, user, subscribtion, ):
    client = APIClient()
    response = client.get("/api/widget/settings/", HTTP_X_API_KEY="not-a-uuid")
    assert response.status_code == 400
    assert "format" in response.json()["error"]
