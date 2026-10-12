"""
Reset MFA osoby z zespołu przez właściciela firmy (2.32.0).

Kategoria ryzyka: DOSTĘP. Decyzja właściciela z 11.10.2026: osoba, która
straciła telefon i kody zapasowe, nie musi przechodzić przez obsługę ani być
usuwana z zespołu (nowe konto, historia pod starym). Zdjęcie ochrony z cudzego
konta jest jednak dokładnie tym, czego chciałby ktoś z przejętą sesją
właściciela - stąd hasło i kod właściciela, koniec sesji osoby, wpis
w dzienniku i mail ostrzegawczy.
"""

from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import totp
from accounts.models import DrugiSkladnik, KodZapasowy, Tenant, WpisDziennika
from accounts.sessions import LoginSession
from accounts.tests.test_drugi_skladnik import wlacz_drugi_skladnik

pytestmark = pytest.mark.django_db

HASLO = "tajne-haslo-2026"


@pytest.fixture
def firma():
    return Tenant.objects.create(name="Rowerownia Krakowska")


def konto(django_user_model, firma, email, rola):
    return django_user_model.objects.create_user(
        username=email, email=email, password=HASLO, tenant=firma, role=rola
    )


@pytest.fixture
def wlascicielka(django_user_model, firma):
    return konto(django_user_model, firma, "szef@rowerownia.pl", "owner")


@pytest.fixture
def pracownik(django_user_model, firma):
    osoba = konto(django_user_model, firma, "serwis@rowerownia.pl", "employee")
    wlacz_drugi_skladnik(osoba)
    for _ in range(2):
        LoginSession.objects.create(
            user=osoba,
            password_fingerprint="f",
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
    return osoba


def klient(kto, firma):
    api = APIClient(HTTP_ORIGIN="https://panel.example.test")
    api.force_authenticate(user=kto)
    api.credentials(HTTP_X_API_KEY=str(firma.api_key))
    return api


def resetuj(api, osoba, **dane):
    return api.post(f"/api/users/{osoba.pk}/reset-mfa/", {"haslo": HASLO, **dane}, format="json")


def test_wlascicielka_resetuje_mfa_pracownika(wlascicielka, pracownik, firma):
    odpowiedz = resetuj(klient(wlascicielka, firma), pracownik)

    assert odpowiedz.status_code == 200
    assert odpowiedz.data == {"zakonczonych_sesji": 2, "ostrzezenie_wyslane": True}
    assert not DrugiSkladnik.objects.filter(uzytkownik=pracownik).exists()
    assert not KodZapasowy.objects.filter(uzytkownik=pracownik).exists()
    # Ktoś, kto przejął telefon razem z zalogowaną kartą, zostaje wylogowany.
    assert not LoginSession.objects.filter(user=pracownik, revoked_at__isnull=True).exists()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [pracownik.email]
    assert "JEŚLI TO NIE TY" in mail.outbox[0].body
    assert wlascicielka.email in mail.outbox[0].body
    wpis = WpisDziennika.objects.get(sciezka=f"/api/users/{pracownik.pk}/reset-mfa/")
    assert wpis.uzytkownik == wlascicielka
    assert wpis.status == 200


def test_bledne_haslo_nic_nie_zmienia(wlascicielka, pracownik, firma):
    odpowiedz = resetuj(klient(wlascicielka, firma), pracownik, haslo="zle-haslo")

    assert odpowiedz.status_code == 400
    assert DrugiSkladnik.objects.filter(uzytkownik=pracownik).exists()
    assert LoginSession.objects.filter(user=pracownik, revoked_at__isnull=True).count() == 2
    assert mail.outbox == []


def test_wlascicielka_z_mfa_musi_podac_wlasny_kod(wlascicielka, pracownik, firma):
    """Przejęta sesja właściciela z jego hasłem nie wystarcza bez jego telefonu."""
    skladnik = wlacz_drugi_skladnik(wlascicielka)
    api = klient(wlascicielka, firma)

    bez_kodu = resetuj(api, pracownik)
    assert bez_kodu.status_code == 400
    assert DrugiSkladnik.objects.filter(uzytkownik=pracownik).exists()

    z_kodem = resetuj(api, pracownik, kod=totp.kod(skladnik.sekret))
    assert z_kodem.status_code == 200
    assert not DrugiSkladnik.objects.filter(uzytkownik=pracownik).exists()


def test_pracownik_nie_resetuje_innych(pracownik, firma, django_user_model):
    kolega = konto(django_user_model, firma, "kolega@rowerownia.pl", "employee")
    wlacz_drugi_skladnik(kolega)

    odpowiedz = resetuj(klient(pracownik, firma), kolega)

    assert odpowiedz.status_code == 403
    assert DrugiSkladnik.objects.filter(uzytkownik=kolega).exists()


def test_osoba_z_innej_firmy_nie_istnieje(wlascicielka, firma, django_user_model):
    obca_firma = Tenant.objects.create(name="Inna")
    obcy = konto(django_user_model, obca_firma, "obcy@inna.pl", "owner")
    wlacz_drugi_skladnik(obcy)

    odpowiedz = resetuj(klient(wlascicielka, firma), obcy)

    assert odpowiedz.status_code == 404
    assert DrugiSkladnik.objects.filter(uzytkownik=obcy).exists()


def test_swoje_mfa_tylko_w_ustawieniach_konta(wlascicielka, firma):
    # Poprawne hasło i kod: jedyną przeszkodą ma być ta reguła. Własne MFA
    # wyłącza się w Ustawieniach konta, gdzie obowiązują własne zasady.
    skladnik = wlacz_drugi_skladnik(wlascicielka)

    odpowiedz = resetuj(klient(wlascicielka, firma), wlascicielka, kod=totp.kod(skladnik.sekret))

    assert odpowiedz.status_code == 400
    assert "Ustawieniach konta" in odpowiedz.json()["detail"]
    assert DrugiSkladnik.objects.filter(uzytkownik=wlascicielka).exists()


def test_osoba_bez_mfa(wlascicielka, firma, django_user_model):
    bez = konto(django_user_model, firma, "bez@rowerownia.pl", "employee")

    odpowiedz = resetuj(klient(wlascicielka, firma), bez)

    assert odpowiedz.status_code == 400
    assert mail.outbox == []


def test_nieudany_mail_nie_cofa_resetu_ale_mowi_o_tym(wlascicielka, pracownik, firma):
    with patch("accounts.mfa_reset.send_mail", side_effect=OSError("SMTP padło")):
        odpowiedz = resetuj(klient(wlascicielka, firma), pracownik)

    assert odpowiedz.status_code == 200
    assert odpowiedz.data["ostrzezenie_wyslane"] is False
    assert not DrugiSkladnik.objects.filter(uzytkownik=pracownik).exists()


def test_stan_mfa_na_liscie_tylko_dla_wlasciciela(wlascicielka, pracownik, firma):
    lista = klient(wlascicielka, firma).get("/api/users/").json()
    wpisy = lista["results"] if isinstance(lista, dict) else lista
    stan = {w["email"]: w["mfa_wlaczone"] for w in wpisy}
    assert stan == {wlascicielka.email: False, pracownik.email: True}

    # Pracownik nie dostaje listy kont bez drugiego składnika.
    lista_pracownika = klient(pracownik, firma).get("/api/users/").json()
    wpisy_pracownika = (
        lista_pracownika["results"] if isinstance(lista_pracownika, dict) else lista_pracownika
    )
    assert all(w["mfa_wlaczone"] is None for w in wpisy_pracownika)
