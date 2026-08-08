import pytest
from rest_framework.test import APIClient
from accounts.models import Tenant
import uuid
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
    data = response.json()

    # Wartości, o które temu testowi faktycznie chodzi
    assert data["widget_position"] == "right"
    assert data["widget_color"] == "#00ff00"
    assert data["widget_title"] == "Zapytaj nas!"
    assert data["branding_mode"] == "smart"

    # Pełen zestaw kluczy trzymany osobno: widget czyta tę odpowiedź wprost,
    # więc usunięcie pola psuje osadzone czaty u wszystkich klientów naraz.
    # Porównanie całego słownika mieszało te dwie sprawy i wywracało się przy
    # każdym nowym polu, nie mówiąc, czy to regresja, czy tylko brak aktualizacji.
    assert set(data) == {
        "widget_position", "widget_color", "widget_title", "branding_mode",
        "widget_footer_text", "widget_logo", "widget_avatar",
        "privacy_policy_url", "widget_welcome_message", "widget_suggested_questions",
    }


@pytest.mark.django_db
def test_widget_settings_invalid_key(api_client, tenant, user, subscribtion):
    api_client.force_authenticate(user=user)
    response = api_client.get("/api/widget-settings/", HTTP_X_API_KEY=str(uuid.uuid4()))
    assert response.status_code == 401

@pytest.mark.django_db
def test_widget_settings_missing_key(api_client, tenant, user, subscribtion):
    api_client.force_authenticate(user=user)
    response = api_client.get("/api/widget-settings/")
    assert response.status_code == 401

@pytest.mark.django_db
def test_widget_settings_invalid_uuid_format(api_client, tenant, user, subscribtion):
    api_client.force_authenticate(user=user)
    with pytest.raises(ValidationError):
        api_client.get("/api/widget-settings/", HTTP_X_API_KEY="not-a-uuid")
