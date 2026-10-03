"""
Kto ma link z panelu, nie zostaje przez to pracownikiem.

Kategoria ryzyka: LINK, KTÓRY JEST HASŁEM. Do 2.20.0 panel podawał właścicielowi
do skopiowania link przyjęcia zaproszenia - ten sam, który zakłada konto. Link
z panelu przekazuje się wtedy, gdy poczta zawiodła, czyli Slackiem, SMS-em,
przez wspólne notatki. Kto go miał, zakładał konto z rolą nadaną przez
właściciela. Formularz wymagał wprawdzie adresu e-mail zaproszenia, ale podgląd
podawał ten adres każdemu, kto miał link, a panel sam wpisywał go w pole -
„sprawdzenie tożsamości" porównywało wartość serwera z nią samą.

Od 2.20.0 zaproszenie ma dwa klucze. Klucz przyjęcia zakłada konto i jedzie
wyłącznie mailem na adres zaproszenia, więc jego posiadanie dowodzi dostępu do
tej skrzynki. Klucz wysyłki trafia do panelu i umie tylko poprosić o wysłanie
zaproszenia na właściwy adres.
"""

import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import CustomUser, InvitationToken, Tenant

pytestmark = pytest.mark.django_db

HASLO = "Bardzo-Dlugie-Haslo-Testowe-2026!"


@pytest.fixture(autouse=True)
def czysty_cache():
    """Odstęp między wysyłkami trzymamy w cache - bez czyszczenia testy by się mieszały."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def firma():
    return Tenant.objects.create(name="Piekarnia")


@pytest.fixture
def wlasciciel(firma):
    osoba = CustomUser.objects.create_user(
        username="szef", email="szef@piekarnia.pl", tenant=firma, role="owner"
    )
    klient = APIClient()
    klient.force_authenticate(user=osoba)
    klient.credentials(HTTP_X_API_KEY=str(firma.api_key))
    return klient


@pytest.fixture
def zaproszenie(firma):
    return InvitationToken.objects.create(
        tenant=firma, email="pracownik@piekarnia.pl", role="employee"
    )


def anonim():
    return APIClient()


def przyjmij(token, username="pracownik", **dodatkowe):
    return anonim().post(
        "/api/accounts/accept-invite/",
        {"token": str(token), "username": username, "password": HASLO, **dodatkowe},
        format="json",
    )


def klucz_z_linku(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


# --- sedno: link z panelu nie zakłada konta -----------------------------------


def test_link_z_panelu_nie_zaklada_konta(wlasciciel, mocker):
    """
    Ten test padał na kodzie sprzed 2.20.0 - i to z właściwego powodu.

    Odtwarzamy dokładnie to, co zrobiłby ktoś, komu link przesłano Slackiem:
    bierze link z panelu, otwiera podgląd, przepisuje z niego adres i zakłada
    konto. Pierwsza wersja tego testu pomijała podgląd i nie wysyłała adresu,
    przez co na starym kodzie też dawała 400 - tyle że za brak pola, a nie
    dzięki jakiejkolwiek ochronie. Test przechodził, a dziurę i tak by przepuścił.
    """
    mocker.patch("api.views.accounts.send_invitation_email")
    odp = wlasciciel.post(
        "/api/accounts/invitations/",
        {"email": "pracownik@piekarnia.pl", "role": "employee", "duration": "1d", "max_users": 1},
        format="json",
    )
    klucz = klucz_z_linku(odp.json()["accept_url"])

    podglad = anonim().get(f"/api/accounts/invitations/{klucz}/preview/")
    adres = podglad.json().get("email", "") if podglad.status_code == 200 else ""
    proba = przyjmij(klucz, email=adres)

    assert proba.status_code == 400
    assert not CustomUser.objects.filter(email="pracownik@piekarnia.pl").exists()


def test_lista_zaproszen_nie_pokazuje_klucza_przyjecia(wlasciciel, zaproszenie):
    odp = wlasciciel.get("/api/accounts/invitations/list/")

    wpis = odp.json()["results"][0] if "results" in odp.json() else odp.json()[0]
    assert "token" not in wpis
    assert str(zaproszenie.token) not in str(odp.json())
    assert wpis["accept_url"].endswith(f"/invite/wyslij/{zaproszenie.token_wysylki}")


def test_podglad_nie_podaje_adresu(zaproszenie):
    """Podgląd odpowiada każdemu, kto ma klucz - nie podsuwa mu adresu do wpisania."""
    odp = anonim().get(f"/api/accounts/invitations/{zaproszenie.token}/preview/")

    assert odp.status_code == 200
    assert "email" not in odp.json()
    assert "pracownik@piekarnia.pl" not in str(odp.json())


# --- przyjęcie kluczem z maila --------------------------------------------------


def test_klucz_z_maila_zaklada_konto_na_adres_zaproszenia(zaproszenie):
    """Adres konta bierzemy z zaproszenia, nie od osoby wypełniającej formularz."""
    odp = przyjmij(zaproszenie.token)

    assert odp.status_code == 201
    osoba = CustomUser.objects.get(username="pracownik")
    assert osoba.email == "pracownik@piekarnia.pl"
    assert osoba.tenant_id == zaproszenie.tenant_id
    assert osoba.role == "employee"


def test_pusty_adres_ze_starego_panelu_dziala(zaproszenie):
    """
    Panel sprzed 2.20.0 wysyła pusty adres, bo nowy podgląd go już nie zwraca.

    Bez tego wdrożenie backendu przed panelem zepsułoby każde przyjęcie
    zaproszenia na czas między jednym a drugim wdrożeniem.
    """
    odp = przyjmij(zaproszenie.token, email="")

    assert odp.status_code == 201
    assert CustomUser.objects.filter(email="pracownik@piekarnia.pl").exists()


def test_podany_cudzy_adres_nadal_jest_odrzucany(zaproszenie):
    odp = przyjmij(zaproszenie.token, email="ktos-inny@example.com")

    assert odp.status_code == 400
    assert not CustomUser.objects.filter(username="pracownik").exists()


def test_klucz_wysylki_nie_dziala_jako_klucz_przyjecia(zaproszenie):
    assert przyjmij(zaproszenie.token_wysylki).status_code == 400
    podglad = anonim().get(f"/api/accounts/invitations/{zaproszenie.token_wysylki}/preview/")
    assert podglad.status_code == 404


def test_istniejace_konto_z_tym_adresem_daje_400_a_nie_500(zaproszenie, firma):
    """Adres bierzemy z zaproszenia, więc unikalność też trzeba sprawdzić na nim."""
    CustomUser.objects.create_user(
        username="juz-jest", email="Pracownik@Piekarnia.pl", tenant=firma
    )

    odp = przyjmij(zaproszenie.token)

    assert odp.status_code == 400


# --- wysyłka kluczem z panelu ---------------------------------------------------


def wyslij(token_wysylki):
    return anonim().post(f"/api/accounts/invitations/wyslij/{token_wysylki}/")


def test_wysylka_trafia_na_adres_zaproszenia_z_kluczem_przyjecia(zaproszenie):
    odp = wyslij(zaproszenie.token_wysylki)

    assert odp.status_code == 202
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["pracownik@piekarnia.pl"]
    assert f"/invite/accept/{zaproszenie.token}" in mail.outbox[0].body
    assert str(zaproszenie.token_wysylki) not in mail.outbox[0].body


def test_odpowiedz_wysylki_nie_zdradza_adresu(zaproszenie):
    odp = wyslij(zaproszenie.token_wysylki)

    assert "pracownik" not in str(odp.json())
    assert "piekarnia" not in str(odp.json())


def test_nieznany_klucz_wysylki_daje_404():
    assert wyslij(uuid.uuid4()).status_code == 404
    assert mail.outbox == []


def test_wykorzystane_zaproszenie_nie_jest_wysylane(zaproszenie):
    zaproszenie.use()

    assert wyslij(zaproszenie.token_wysylki).status_code == 410
    assert mail.outbox == []


def test_wygasle_zaproszenie_nie_jest_wysylane(zaproszenie):
    InvitationToken.objects.filter(pk=zaproszenie.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )

    assert wyslij(zaproszenie.token_wysylki).status_code == 410
    assert mail.outbox == []


def test_drugi_klik_w_ciagu_minuty_nie_wysyla_drugiej_wiadomosci(zaproszenie):
    """
    Link krąży po wspólnym kanale, więc nie może być narzędziem do zasypywania
    czyjejś skrzynki. Odpowiedź jest ta sama - drugi klik to nie błąd osoby,
    która po prostu nie widzi jeszcze wiadomości.
    """
    pierwsza = wyslij(zaproszenie.token_wysylki)
    druga = wyslij(zaproszenie.token_wysylki)

    assert pierwsza.status_code == druga.status_code == 202
    assert len(mail.outbox) == 1


def test_nieudana_wysylka_pozwala_sprobowac_ponownie(zaproszenie, mocker):
    """Awaria poczty nie może zablokować ponowienia na minutę."""
    mocker.patch(
        "api.views.accounts.send_invitation_email", side_effect=OSError("SMTP niedostępny")
    )
    assert wyslij(zaproszenie.token_wysylki).status_code == 503

    mocker.stopall()
    assert wyslij(zaproszenie.token_wysylki).status_code == 202
    assert len(mail.outbox) == 1


def test_kazde_zaproszenie_ma_wlasny_klucz_wysylki(firma):
    klucze = {
        InvitationToken.objects.create(tenant=firma, email=f"osoba{i}@example.com").token_wysylki
        for i in range(5)
    }

    assert len(klucze) == 5


# --- migracja -------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_migracja_nadaje_rozne_klucze_istniejacym_zaproszeniom():
    """
    `AddField` z `default=uuid4` i `unique` nadałby wszystkim istniejącym
    wierszom TĘ SAMĄ wartość - Django wylicza ją raz na migrację - i migracja
    padłaby na drugim zaproszeniu. Testy migrują pustą bazę, więc bez tego
    testu nic nie sprawdziłoby przypadku, który jest na produkcji.
    """
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    najnowsze = executor.loader.graph.leaf_nodes()
    przed = [("accounts", "0045_przebieg_monitora")]
    po = [("accounts", "0046_zaproszenie_token_wysylki")]
    executor.migrate(przed)
    stare = executor.loader.project_state(przed).apps
    Firma = stare.get_model("accounts", "Tenant")
    Zaproszenie = stare.get_model("accounts", "InvitationToken")
    firma = Firma.objects.create(name="Migracja")
    for i in range(3):
        Zaproszenie.objects.create(tenant=firma, email=f"osoba{i}@example.com")
    try:
        MigrationExecutor(connection).migrate(po)
        nowe = MigrationExecutor(connection).loader.project_state(po).apps
        klucze = list(
            nowe.get_model("accounts", "InvitationToken")
            .objects.filter(tenant_id=firma.pk)
            .values_list("token_wysylki", flat=True)
        )
        assert len(klucze) == 3
        assert None not in klucze
        assert len(set(klucze)) == 3
    finally:
        MigrationExecutor(connection).migrate(najnowsze)
        Tenant.objects.filter(name="Migracja").delete()
