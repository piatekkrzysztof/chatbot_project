"""
Klucz przyjęcia zaproszenia nie jedzie w adresie żądania (A-26, 2.32.18).

Kategoria ryzyka: KLUCZ W LOGACH. Klucz przyjęcia zakłada konto w firmie
z rolą z zaproszenia, także właściciela. Do 2.32.17 był w ścieżce linku z maila
(`/invite/accept/<klucz>`) i w ścieżce podglądu
(`GET /api/accounts/invitations/<klucz>/preview/`), więc lądował w logach
zapytań hostingu panelu i API. Fragment adresu (`#token=...`) przeglądarka
zostawia u siebie, a podgląd dostaje klucz w treści POST - tak jak już działają
reset hasła i aktywacja konta.
"""

import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import InvitationToken, Tenant
from accounts.utils.email import send_invitation_email
from api.registration_throttles import InvitationPreviewThrottle

pytestmark = pytest.mark.django_db

PODGLAD = "/api/accounts/invitations/preview/"


@pytest.fixture(autouse=True)
def czysty_cache():
    """Licznik limitu zapytań leży w cache - bez czyszczenia testy by się mieszały."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def zaproszenie():
    firma = Tenant.objects.create(name="Piekarnia")
    return InvitationToken.objects.create(
        tenant=firma, email="pracownik@piekarnia.pl", role="employee"
    )


def podglad(dane):
    # Tak jak panel: JSON, bez ciasteczek i bez nagłówka CSRF.
    return APIClient(enforce_csrf_checks=True).post(PODGLAD, dane, format="json")


# --- podgląd POST-em -------------------------------------------------------------


def test_podglad_przyjmuje_klucz_w_tresci(zaproszenie):
    odp = podglad({"token": str(zaproszenie.token)})

    assert odp.status_code == 200
    dane = odp.json()
    assert set(dane) == {"company", "role", "is_valid", "expires_at"}
    assert dane["company"] == "Piekarnia"
    assert dane["role"] == "employee"
    assert dane["is_valid"] is True
    assert "pracownik@piekarnia.pl" not in str(dane)


def test_stary_podglad_z_kluczem_w_sciezce_nie_istnieje(zaproszenie):
    """
    GET z kluczem w adresie został na tydzień dla linków sprzed 2.32.18 i
    zniknął w 2.32.25 (przegląd 2026-11, R08). Nie odpowiada ani nie zdradza
    firmy - także ważnemu kluczowi.
    """
    stary = APIClient().get(f"/api/accounts/invitations/{zaproszenie.token}/preview/")

    assert stary.status_code in (401, 404)
    assert "Piekarnia" not in stary.content.decode()


def test_nieznany_klucz_daje_404():
    odp = podglad({"token": str(uuid.uuid4())})

    assert odp.status_code == 404
    assert odp.json() == {"detail": "Nieprawidłowy link zaproszenia."}


def test_klucz_wysylki_nie_otwiera_podgladu(zaproszenie):
    assert podglad({"token": str(zaproszenie.token_wysylki)}).status_code == 404


@pytest.mark.parametrize("klucz", ["nie-uuid", "", "1234", ["a"], None])
def test_zle_zbudowany_klucz_daje_400(klucz):
    assert podglad({"token": klucz}).status_code == 400


def test_brak_klucza_daje_400():
    assert podglad({}).status_code == 400


def test_wykorzystane_zaproszenie_nie_jest_wazne(zaproszenie):
    zaproszenie.use()

    odp = podglad({"token": str(zaproszenie.token)})

    assert odp.status_code == 200
    assert odp.json()["is_valid"] is False


def test_wygasle_zaproszenie_nie_jest_wazne(zaproszenie):
    InvitationToken.objects.filter(pk=zaproszenie.pk).update(
        created_at=timezone.now() - timedelta(days=8)
    )

    odp = podglad({"token": str(zaproszenie.token)})

    assert odp.status_code == 200
    assert odp.json()["is_valid"] is False


def test_podglad_ma_limit_prob(zaproszenie, monkeypatch):
    """Zgadywanie kluczy podglądem kończy się na limicie prób z jednego adresu."""
    monkeypatch.setattr(InvitationPreviewThrottle, "ip_limit", 2)

    podglad({"token": str(zaproszenie.token)})
    podglad({"token": str(zaproszenie.token)})

    assert podglad({"token": str(zaproszenie.token)}).status_code == 429


# --- link w mailu ----------------------------------------------------------------


@pytest.mark.parametrize(
    "adres_panelu", ["https://panel.example.test", "https://panel.example.test/"]
)
def test_link_w_mailu_ma_klucz_we_fragmencie(zaproszenie, settings, adres_panelu):
    settings.FRONTEND_URL = adres_panelu

    send_invitation_email(zaproszenie)

    tresc = mail.outbox[0].body
    link = next(slowo for slowo in tresc.split() if slowo.startswith("https://"))
    czesci = urlsplit(link)
    assert link == f"https://panel.example.test/invite/accept#token={zaproszenie.token}"
    assert str(zaproszenie.token) not in czesci.path + czesci.query
    assert czesci.fragment == f"token={zaproszenie.token}"
