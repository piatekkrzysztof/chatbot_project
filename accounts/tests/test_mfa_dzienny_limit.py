"""
Dobowy limit błędnych kodów drugiego kroku i ostrzeżenie dla właściciela konta (2.32.14).

Do 2.32.13 jedyną granicą był limit konta: 10 prób na 5 minut, bez końca. Kto
znał hasło, miał 2880 prób na dobę, czyli ok. 0,9% szans dziennie na trafienie
kodu (3 ważne kody z miliona) - a osoba, której hasło wyciekło, nie dowiadywała
się o niczym (audyt 2026-10, P16).

Teraz 20 błędnych kodów w ciągu doby zamyka drugi krok tego konta - także dla
poprawnego kodu - i wysyła jedno ostrzeżenie mailem. Licznik jest związany
z hasłem: zmiana hasła, którą mail radzi, od razu zdejmuje blokadę.
"""

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import dwuskladnikowe, totp
from accounts.models import CustomUser, DrugiSkladnik, Tenant

ORIGIN = "https://panel.example.test"


@pytest.fixture(autouse=True)
def czysty_licznik(monkeypatch):
    cache.clear()
    # Limit 10 prób na 5 minut działa dalej, ale tu przeszkadza: test sprawdza
    # granicę dobową, do której przy nim dochodzi się dopiero po godzinie.
    monkeypatch.setattr("api.mfa_throttles.account_attempt", lambda user: None)
    yield
    cache.clear()


@pytest.fixture
def konto(db):
    firma = Tenant.objects.create(name="MFA")
    osoba = CustomUser.objects.create_user(
        username="mfa", email="mfa@example.com", password="haslo-2026-x", tenant=firma
    )
    DrugiSkladnik.objects.create(
        uzytkownik=osoba, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
    )
    return osoba


def zly_kod(konto, ile):
    for numer in range(ile):
        if numer % 5 == 0:
            bilet = dwuskladnikowe.wystaw_bilet(konto)
        assert dwuskladnikowe.zakoncz_logowanie(bilet, "000000") == (None, 400)


def dobry_kod_przez_api(konto, adres="203.0.113.30"):
    skladnik = DrugiSkladnik.objects.get(uzytkownik=konto)
    bilet = dwuskladnikowe.wystaw_bilet(CustomUser.objects.get(pk=konto.pk))
    return APIClient(HTTP_ORIGIN=ORIGIN).post(
        "/api/accounts/login/2fa/",
        {"bilet": bilet, "kod": totp.kod(skladnik.sekret)},
        format="json",
        REMOTE_ADDR=adres,
    )


@pytest.mark.django_db
class TestDobowyLimit:
    def test_ponizej_limitu_dobry_kod_loguje(self, konto):
        zly_kod(konto, dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW - 1)

        odpowiedz = dobry_kod_przez_api(konto)

        assert odpowiedz.status_code == 200
        assert "access" in odpowiedz.json()

    def test_po_limicie_nawet_dobry_kod_nie_loguje(self, konto):
        zly_kod(konto, dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW)

        odpowiedz = dobry_kod_przez_api(konto)

        assert odpowiedz.status_code == 429
        assert "access" not in odpowiedz.json()

    def test_zmiana_hasla_zdejmuje_blokade(self, konto):
        zly_kod(konto, dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW)
        konto.set_password("nowe-haslo-2026-y")
        konto.save()

        assert dobry_kod_przez_api(konto).status_code == 200

    def test_blokada_dotyczy_tylko_tego_konta(self, konto):
        zly_kod(konto, dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW)
        drugie = CustomUser.objects.create_user(
            username="mfa2", email="mfa2@example.com", password="haslo-2026-x", tenant=konto.tenant
        )
        DrugiSkladnik.objects.create(
            uzytkownik=drugie, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
        )

        assert dobry_kod_przez_api(drugie).status_code == 200


@pytest.mark.django_db
class TestOstrzezenie:
    def test_jedno_ostrzezenie_przy_osiagnieciu_limitu(
        self, konto, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            zly_kod(konto, dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW - 1)
        assert mail.outbox == []

        with django_capture_on_commit_callbacks(execute=True):
            zly_kod(konto, 1)
            dwuskladnikowe.zakoncz_logowanie(dwuskladnikowe.wystaw_bilet(konto), "000000")

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["mfa@example.com"]
        assert "hasło" in mail.outbox[0].body


# --- logowanie do panelu administracyjnego Django (przegląd 2026-11, R12) -----


@pytest.fixture
def administrator(konto, monkeypatch):
    # admin_security importuje account_attempt bezpośrednio; limit adresu IP
    # (MfaThrottle) też tu przeszkadza z tego samego powodu co wyżej.
    monkeypatch.setattr("accounts.admin_security.account_attempt", lambda user: None)
    monkeypatch.setattr(
        "accounts.admin_security.MfaThrottle.allow_request", lambda self, request, view: True
    )
    CustomUser.objects.filter(pk=konto.pk).update(is_staff=True)
    konto.refresh_from_db()
    return konto


def logowanie_admina(osoba, kod, haslo="haslo-2026-x"):
    from django.test import Client

    klient = Client()
    odpowiedz = klient.post(
        "/admin/login/?next=/admin/",
        {"username": osoba.username, "password": haslo, "kod": kod, "next": "/admin/"},
    )
    return odpowiedz, "_auth_user_id" in klient.session


def dobry_kod(osoba):
    return totp.kod(DrugiSkladnik.objects.get(uzytkownik=osoba).sekret)


@pytest.mark.django_db
class TestLogowanieAdmina:
    """
    Do 2.32.28 logowanie admina sprawdzało kod tym samym kodem co panel, ale bez
    dobowego licznika: przy znanym haśle konta z dostępem do całej platformy
    zgadywanie kodu trwało bez końca i bez wiadomości do osoby.
    """

    def test_bledne_kody_admina_licza_sie_do_dobowego_limitu(self, administrator):
        for _ in range(dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW):
            _, zalogowany = logowanie_admina(administrator, "000000")
            assert not zalogowany

        odpowiedz, zalogowany = logowanie_admina(administrator, dobry_kod(administrator))

        assert not zalogowany
        assert "wstrzymane na dobę" in odpowiedz.content.decode()

    def test_ostrzezenie_wychodzi_mimo_bledu_formularza(
        self, administrator, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            for _ in range(dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW):
                logowanie_admina(administrator, "000000")

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["mfa@example.com"]

    def test_licznik_wspolny_z_panelem(self, administrator):
        zly_kod(administrator, dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW)

        _, zalogowany = logowanie_admina(administrator, dobry_kod(administrator))

        assert not zalogowany

    def test_ponizej_limitu_admin_loguje_sie_jak_dotad(self, administrator):
        for _ in range(dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW - 1):
            logowanie_admina(administrator, "000000")

        odpowiedz, zalogowany = logowanie_admina(administrator, dobry_kod(administrator))

        assert zalogowany
        assert odpowiedz.status_code == 302

    def test_zmiana_hasla_zdejmuje_blokade_admina(self, administrator):
        for _ in range(dwuskladnikowe.DOBOWY_LIMIT_BLEDNYCH_KODOW):
            logowanie_admina(administrator, "000000")
        administrator.set_password("nowe-haslo-2026-y")
        administrator.save()

        _, zalogowany = logowanie_admina(
            administrator, dobry_kod(administrator), haslo="nowe-haslo-2026-y"
        )

        assert zalogowany
