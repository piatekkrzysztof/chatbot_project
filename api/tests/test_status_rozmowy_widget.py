"""
Widget pyta przy otwarciu, czy firma nie usunęła jego rozmowy.

Kategoria ryzyka: USUNIĘCIE, KTÓRE WYGLĄDA NA NIEUDANE. Widget trzyma historię
w przeglądarce odwiedzającego i pokazywał ją bez pytania serwera. Odbiór
5.10.2026: właściciel usunął rozmowę w panelu, a w przeglądarce została
w całości - odwiedzający, który prosił o usunięcie, uznałby, że go nie było.

Te testy pilnują backendu: odpowiedź „usunięta" pada po usunięciu przez wspólny protokół
(ręcznie lub przez retencję), nigdy dla rozmowy, której po prostu nie ma.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Tenant
from chat.lifecycle import usun_rozmowe
from chat.models import Conversation, UsunietaRozmowa
from chat.retention import purge_tenant

pytestmark = pytest.mark.django_db


def zapytaj(tenant, session_id, klucz=True):
    klient = APIClient()
    naglowki = {"HTTP_X_API_KEY": str(tenant.api_key)} if klucz else {}
    return klient.get(f"/api/widget/rozmowa/{session_id}/", **naglowki)


def rozmowa(tenant):
    return Conversation.objects.create(tenant=tenant, user_identifier="gosc")


def test_usunieta_przez_firme_daje_410(tenant, subscribtion):
    """Ten sam kod co przy próbie pisania w usuniętej rozmowie - widget już go rozumie."""
    r = rozmowa(tenant)
    usun_rozmowe(tenant, r.session_id)

    odp = zapytaj(tenant, r.session_id)

    # Widget rozpoznaje usunięcie po samym statusie 410 (WidgetChat.tsx),
    # tak samo jak przy próbie pisania w usuniętej rozmowie.
    assert odp.status_code == 410
    assert odp.json() == {"detail": "Rozmowa została usunięta. Rozpocznij nową rozmowę."}


def test_istniejaca_rozmowa_daje_204(tenant, subscribtion):
    odp = zapytaj(tenant, rozmowa(tenant).session_id)

    assert odp.status_code == 204


def test_nieznana_rozmowa_nie_jest_usunieta(tenant, subscribtion):
    """
    Rozmowa, której nie ma, to nie to samo co rozmowa usunięta.

    Odwiedzający, którego pierwsza wiadomość nie doszła, ma w przeglądarce
    identyfikator, którego serwer nigdy nie widział. Nie może przez to
    stracić tego, co napisał.
    """
    odp = zapytaj(tenant, uuid.uuid4())

    assert odp.status_code == 204


def test_brak_rozmowy_bez_znacznika_nie_dowodzi_usuniecia(tenant, subscribtion):
    """Surowe ORM delete nie jest ścieżką retencji; sam brak nie uzasadnia 410."""
    r = rozmowa(tenant)
    sesja = r.session_id
    r.delete()

    assert zapytaj(tenant, sesja).status_code == 204


def test_usuniecie_w_innej_firmie_nie_przecieka(tenant, subscribtion):
    """Znacznik należy do firmy; ta sama sesja w innej firmie nic tu nie znaczy."""
    obca = Tenant.objects.create(name="Obca")
    r = rozmowa(obca)
    usun_rozmowe(obca, r.session_id)

    assert zapytaj(tenant, r.session_id).status_code == 204


def test_bez_klucza_api_odmowa(tenant, subscribtion):
    odp = zapytaj(tenant, uuid.uuid4(), klucz=False)

    assert odp.status_code in (401, 403)


def test_pytanie_niczego_nie_tworzy(tenant, subscribtion):
    """Odczyt stanu nie może otworzyć rozmowy - inaczej każde wejście na stronę by ją zakładało."""
    przed = Conversation.objects.count()

    zapytaj(tenant, uuid.uuid4())

    assert Conversation.objects.count() == przed


def test_rzeczywista_retencja_daje_410_i_nie_odtwarza_sesji(tenant, subscribtion):
    """Widget musi wyczyścić także historię usuniętą przez purge_tenant."""
    tenant.data_retention_days = 30
    tenant.save(update_fields=["data_retention_days"])
    r = rozmowa(tenant)
    Conversation.objects.filter(pk=r.pk).update(last_message_at=timezone.now() - timedelta(days=40))

    wynik = purge_tenant(tenant)

    assert wynik["Conversation"] == 1
    assert not Conversation.objects.filter(pk=r.pk).exists()
    assert UsunietaRozmowa.objects.filter(tenant=tenant).exists()
    assert zapytaj(tenant, r.session_id).status_code == 410
    klient = APIClient()
    powtorka = klient.post(
        "/api/widget/chat/",
        {"message": "Spóźnione pytanie", "conversation_session_id": str(r.session_id)},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )
    assert powtorka.status_code == 410
    assert not Conversation.objects.filter(session_id=r.session_id).exists()
