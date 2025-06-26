import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
import uuid
from rest_framework.exceptions import AuthenticationFailed
from django.core.exceptions import ValidationError


@pytest.mark.django_db
def test_widget_settings_success(api_client, tenant, user, subscribtion, ):
    tenant.widget_position = "right"
    tenant.widget_color = "#00ff00"
    tenant.widget_title = "Zapytaj nas!"
    tenant.save()
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
def test_widget_settings_invalid_key(api_client, tenant, user, subscribtion):
    api_client.force_authenticate(user=user)
    with pytest.raises(AuthenticationFailed):
        api_client.get("/api/widget-settings/", HTTP_X_API_KEY=str(uuid.uuid4()))

@pytest.mark.django_db
def test_widget_settings_missing_key(api_client, tenant, user, subscribtion):
    api_client.force_authenticate(user=user)
    with pytest.raises(AuthenticationFailed):
        api_client.get("/api/widget-settings/")

@pytest.mark.django_db
def test_widget_settings_invalid_uuid_format(api_client, tenant, user, subscribtion):
    api_client.force_authenticate(user=user)
    with pytest.raises(ValidationError):
        api_client.get("/api/widget-settings/", HTTP_X_API_KEY="not-a-uuid")
