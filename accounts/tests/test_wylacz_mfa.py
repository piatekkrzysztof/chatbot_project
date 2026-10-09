"""
Polecenie wylacz_mfa - ostatni krok procedury utraty telefonu (docs/utrata-mfa.md).

Kategoria ryzyka: DOSTĘP. Wyłączenie drugiego składnika to dokładnie to, o co
poprosiłby ktoś, kto ukradł hasło. Dlatego polecenie robi pełny komplet albo
nic: usuwa składnik i kody, kończy sesje (przejęta sesja nie może przetrwać),
zapisuje ślad w dzienniku i ostrzega właściciela konta mailem - to on pierwszy
zauważy wyłączenie, którego nie zlecał.
"""

from unittest.mock import patch

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts.models import DrugiSkladnik, KodZapasowy, Tenant, WpisDziennika
from accounts.sessions import LoginSession
from accounts.tests.test_drugi_skladnik import wlacz_drugi_skladnik

pytestmark = pytest.mark.django_db

ZGLOSZENIE = "telefon 9.10 12:05, oddzwonienie na numer z danych do faktury"


@pytest.fixture
def osoba(django_user_model):
    firma = Tenant.objects.create(name="Cukiernia Testowa")
    uzytkownik = django_user_model.objects.create_user(
        username="szefowa@cukiernia.test",
        email="szefowa@cukiernia.test",
        password="x",
        tenant=firma,
        role="owner",
    )
    wlacz_drugi_skladnik(uzytkownik)
    for _ in range(2):
        LoginSession.objects.create(
            user=uzytkownik,
            password_fingerprint="f",
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
    return uzytkownik


def uruchom(*argumenty):
    try:
        call_command("wylacz_mfa", *argumenty)
        return 0
    except SystemExit as wyjscie:
        return wyjscie.code


def test_bez_wykonaj_nic_nie_zmienia(osoba):
    uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE)

    assert DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert KodZapasowy.objects.filter(uzytkownik=osoba).exists()
    assert LoginSession.objects.filter(user=osoba, revoked_at__isnull=True).count() == 2
    assert mail.outbox == []


def test_wykonaj_robi_caly_komplet(osoba):
    kod = uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert kod == 0
    assert not DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert not KodZapasowy.objects.filter(uzytkownik=osoba).exists()
    # Przejęta sesja nie może przetrwać wyłączenia ochrony.
    assert not LoginSession.objects.filter(user=osoba, revoked_at__isnull=True).exists()
    wpis = WpisDziennika.objects.get(tenant=osoba.tenant, metoda="CLI")
    assert wpis.uzytkownik == osoba
    assert ZGLOSZENIE in wpis.sciezka
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [osoba.email]
    assert "JEŚLI TO NIE TY" in mail.outbox[0].body


def test_adres_bez_wzgledu_na_wielkosc_liter(osoba):
    uruchom("--email", osoba.email.upper(), "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert not DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()


def test_bez_opisu_weryfikacji_odmawia(osoba):
    """Opis weryfikacji to jedyny ślad decyzji - polecenie nie ruszy bez niego."""
    with pytest.raises(CommandError, match="zgloszenie"):
        uruchom("--email", osoba.email, "--zgloszenie", "  ok ", "--wykonaj")

    assert DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()


def test_nieznany_adres(osoba):
    with pytest.raises(CommandError, match="Nie ma konta"):
        uruchom("--email", "ktos@obcy.test", "--zgloszenie", ZGLOSZENIE, "--wykonaj")


def test_konto_bez_mfa_nie_jest_ruszane(osoba):
    DrugiSkladnik.objects.filter(uzytkownik=osoba).delete()

    uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert LoginSession.objects.filter(user=osoba, revoked_at__isnull=True).count() == 2
    assert not WpisDziennika.objects.filter(metoda="CLI").exists()
    assert mail.outbox == []


def test_nieudany_mail_zostawia_wylaczenie_i_mowi_o_tym(osoba, capsys):
    """Cofanie nic by nie dało - ale operator musi wiedzieć, że ostrzeżenie nie poszło."""
    with patch(
        "accounts.management.commands.wylacz_mfa.send_mail", side_effect=OSError("SMTP padło")
    ):
        kod = uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert kod == 1
    assert not DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert "NIE wyszło" in capsys.readouterr().out
