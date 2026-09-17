"""
Zajętość bazy wiedzy widoczna, zanim wgranie się nie uda.

Kategoria ryzyka: NIEWIDOCZNY LIMIT. Klient dowiadywał się o przekroczeniu
dopiero przy nieudanym wgraniu - po przygotowaniu pliku i czekaniu na odczyt.
Po zejściu z wyższego planu nie dowiadywał się w ogóle, dopóki czegoś nie dodał,
choć od tej chwili nie mógł już bazy powiększać.

Pasek w panelu ma pokazywać ten sam rozmiar, którym mierzy limit: długość
wyodrębnionego tekstu, nie rozmiar plików. Dwie różne miary znaczyłyby, że
pasek pokazuje 60%, a wgranie odbija się od limitu.
"""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription
from documents.models import Document
from documents.validators import MB

pytestmark = pytest.mark.django_db


def klient(tenant, rola="viewer"):
    uzytkownik = CustomUser.objects.create_user(username=f"kto-{rola}", tenant=tenant, role=rola)
    api = APIClient()
    api.force_authenticate(user=uzytkownik)
    api.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return api


def uzycie(tenant, rola="viewer"):
    odpowiedz = klient(tenant, rola).get(reverse("documents-uzycie"))
    assert odpowiedz.status_code == 200
    return odpowiedz.json()


def test_zajetosc_liczona_z_tekstu_a_nie_z_plikow(tenant, subscribtion):
    # Strona z importu witryny nie ma pliku, a wiedzą jest tak samo.
    Document.objects.create(tenant=tenant, name="Cennik", content="c" * MB)
    Document.objects.create(tenant=tenant, name="Strona", content="s" * MB, source="website")

    dane = uzycie(tenant)

    assert dane["zajete_bajty"] == 2 * MB
    assert dane["limit_mb"] == 5
    assert dane["procent"] == 40
    assert dane["ponad_limitem"] is False


def test_po_obnizeniu_planu_procent_przekracza_sto(tenant):
    Subscription.objects.create(
        tenant=tenant,
        plan_type="start",
        is_active=True,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
    )
    Document.objects.create(tenant=tenant, name="Wiedza z Pro", content="w" * (8 * MB))

    dane = uzycie(tenant)

    # Przycięcie do 100% ukryłoby dokładnie ten stan, dla którego ten pasek
    # powstał: klient ponad limitem, który nie może już nic dodać.
    assert dane["procent"] == 160
    assert dane["ponad_limitem"] is True


def test_pusta_baza_to_zero_procent(tenant, subscribtion):
    dane = uzycie(tenant)

    assert dane["zajete_bajty"] == 0
    assert dane["procent"] == 0


def test_podglad_widzi_zajetosc(tenant, subscribtion):
    # Rola do oglądania ma widzieć, ile miejsca zostało - nie może dodawać,
    # ale to ona najczęściej pilnuje porządku w bazie wiedzy.
    Document.objects.create(tenant=tenant, name="Cennik", content="c" * MB)

    assert uzycie(tenant, "viewer")["zajete_bajty"] == MB
    assert uzycie(tenant, "employee")["zajete_bajty"] == MB
    assert uzycie(tenant, "owner")["zajete_bajty"] == MB


def test_zajetosc_nie_obejmuje_innej_firmy(tenant, subscribtion, django_user_model):
    from accounts.models import Tenant

    obca = Tenant.objects.create(name="Obca")
    Document.objects.create(tenant=obca, name="Cudze", content="x" * (3 * MB))
    Document.objects.create(tenant=tenant, name="Moje", content="m" * MB)

    assert uzycie(tenant)["zajete_bajty"] == MB
