"""
Przechodzi po wszystkich ekranach panelu Django.

Sprawdzenia Django nie walidują `search_fields` ani wyliczanych pól w
`readonly_fields`, więc takie błędy wychodzą dopiero w produkcji (dwa już
wyszły: expires_at na formularzu zaproszenia i search_fields='title'
w dokumentach). Ten test przechodzi listę, wyszukiwanie i formularz dodawania
dla każdego zarejestrowanego modelu, żeby kolejne wychodziły tutaj.
"""
import pytest
from django.contrib import admin
from django.urls import reverse

from accounts.models import CustomUser


def admin_models():
    return [
        (model._meta.app_label, model._meta.model_name)
        for model in admin.site._registry
    ]


@pytest.fixture
def admin_user(db, tenant):
    user = CustomUser.objects.create_superuser(
        username="admin-sweep@firma.pl",
        email="admin-sweep@firma.pl",
        password="Tajne123!",
        tenant=tenant,
    )
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("app_label,model_name", admin_models())
def test_changelist_opens(client, admin_user, app_label, model_name):
    client.force_login(admin_user)
    url = reverse(f"admin:{app_label}_{model_name}_changelist")

    assert client.get(url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("app_label,model_name", admin_models())
def test_search_works(client, admin_user, app_label, model_name):
    """Wyszukiwanie po nieistniejącym polu rzuca FieldError — łapiemy to tutaj."""
    client.force_login(admin_user)
    url = reverse(f"admin:{app_label}_{model_name}_changelist")

    assert client.get(url, {"q": "test"}).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("app_label,model_name", admin_models())
def test_add_form_opens(client, admin_user, app_label, model_name):
    client.force_login(admin_user)
    url = reverse(f"admin:{app_label}_{model_name}_add")

    response = client.get(url)
    # 403 jest w porządku, gdy model celowo nie pozwala na dodawanie
    assert response.status_code in (200, 403)
