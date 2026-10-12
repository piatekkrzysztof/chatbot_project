"""
Polecenie wylacz_mfa - ostatni krok procedury utraty telefonu (docs/utrata-mfa.md).

Kategoria ryzyka: DOSTĘP. Wyłączenie drugiego składnika to dokładnie to, o co
poprosiłby ktoś, kto ukradł hasło. Dlatego polecenie robi pełny komplet albo
nic: usuwa składnik i kody, kończy sesje (przejęta sesja nie może przetrwać),
zapisuje ślad w dzienniku i ostrzega właściciela konta mailem - to on pierwszy
zauważy wyłączenie, którego nie zlecał.

Od 2.32.0 (decyzja właściciela z 11.10.2026) między prośbą a wyłączeniem musi
minąć doba od zapowiedzi wysłanej na adres konta.
"""

from datetime import timedelta
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


def zapowiedziane(osoba, godzin_temu):
    """Zapowiedź tak, jak zapisuje ją polecenie, przesunięta w czasie."""
    uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--zapowiedz")
    WpisDziennika.objects.filter(sciezka__startswith="wylacz_mfa zapowiedz").update(
        czas=timezone.now() - timedelta(hours=godzin_temu)
    )
    mail.outbox.clear()


def test_bez_opcji_nic_nie_zmienia(osoba):
    uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE)

    assert DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert KodZapasowy.objects.filter(uzytkownik=osoba).exists()
    assert LoginSession.objects.filter(user=osoba, revoked_at__isnull=True).count() == 2
    assert mail.outbox == []
    assert not WpisDziennika.objects.exists()


def test_zapowiedz_ostrzega_i_niczego_nie_wylacza(osoba):
    kod = uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--zapowiedz")

    assert kod == 0
    assert DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert LoginSession.objects.filter(user=osoba, revoked_at__isnull=True).count() == 2
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [osoba.email]
    assert "JEŚLI TO NIE TY" in mail.outbox[0].body
    wpis = WpisDziennika.objects.get(metoda="CLI")
    assert wpis.sciezka.startswith("wylacz_mfa zapowiedz")
    assert ZGLOSZENIE in wpis.sciezka


def test_wykonaj_bez_zapowiedzi_odmawia(osoba):
    with pytest.raises(CommandError, match="zapowiedz"):
        uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert mail.outbox == []


def test_wykonaj_przed_uplywem_doby_odmawia(osoba):
    """Prawdziwy właściciel ma dobę, żeby zareagować na zapowiedź."""
    zapowiedziane(osoba, godzin_temu=23)

    with pytest.raises(CommandError, match="nie minęła doba"):
        uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()


def test_zbyt_stara_zapowiedz_nie_wystarcza(osoba):
    zapowiedziane(osoba, godzin_temu=24 * 8)

    with pytest.raises(CommandError, match="Brak zapowiedzi"):
        uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()


def test_nieudany_mail_zapowiedzi_nie_odblokowuje_wykonania(osoba):
    """Bez wysłanego ostrzeżenia doba oczekiwania nikogo nie chroni."""
    with patch(
        "accounts.management.commands.wylacz_mfa.send_mail", side_effect=OSError("SMTP padło")
    ):
        kod = uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--zapowiedz")

    assert kod == 1
    assert not WpisDziennika.objects.exists()


def test_wykonaj_po_dobie_robi_caly_komplet(osoba):
    zapowiedziane(osoba, godzin_temu=25)

    kod = uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert kod == 0
    assert not DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert not KodZapasowy.objects.filter(uzytkownik=osoba).exists()
    # Przejęta sesja nie może przetrwać wyłączenia ochrony.
    assert not LoginSession.objects.filter(user=osoba, revoked_at__isnull=True).exists()
    wpis = WpisDziennika.objects.get(sciezka__startswith="wylacz_mfa: ")
    assert wpis.uzytkownik == osoba
    assert wpis.tenant == osoba.tenant
    assert ZGLOSZENIE in wpis.sciezka
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [osoba.email]
    assert "JEŚLI TO NIE TY" in mail.outbox[0].body


def test_adres_bez_wzgledu_na_wielkosc_liter(osoba):
    zapowiedziane(osoba, godzin_temu=25)

    uruchom("--email", osoba.email.upper(), "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert not DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()


def test_bez_opisu_weryfikacji_odmawia(osoba):
    """Opis weryfikacji to jedyny ślad decyzji - polecenie nie ruszy bez niego."""
    with pytest.raises(CommandError, match="zgloszenie"):
        uruchom("--email", osoba.email, "--zgloszenie", "  ok ", "--zapowiedz")

    assert mail.outbox == []


def test_nieznany_adres(osoba):
    with pytest.raises(CommandError, match="Nie ma konta"):
        uruchom("--email", "ktos@obcy.test", "--zgloszenie", ZGLOSZENIE, "--wykonaj")


def test_konto_bez_mfa_nie_jest_ruszane(osoba):
    DrugiSkladnik.objects.filter(uzytkownik=osoba).delete()

    uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--zapowiedz")

    assert LoginSession.objects.filter(user=osoba, revoked_at__isnull=True).count() == 2
    assert not WpisDziennika.objects.filter(metoda="CLI").exists()
    assert mail.outbox == []


def test_nieudany_mail_po_wylaczeniu_zostawia_wylaczenie_i_mowi_o_tym(osoba, capsys):
    """Cofanie nic by nie dało - ale operator musi wiedzieć, że ostrzeżenie nie poszło."""
    zapowiedziane(osoba, godzin_temu=25)
    with patch("accounts.mfa_reset.send_mail", side_effect=OSError("SMTP padło")):
        kod = uruchom("--email", osoba.email, "--zgloszenie", ZGLOSZENIE, "--wykonaj")

    assert kod == 1
    assert not DrugiSkladnik.objects.filter(uzytkownik=osoba).exists()
    assert "NIE wyszło" in capsys.readouterr().out
