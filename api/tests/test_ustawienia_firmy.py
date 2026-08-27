"""
Ustawienia firmy w panelu.

Powstały z konkretnego braku: strona Zapytania przy nieudanym powiadomieniu
radzi "uzupełnij adres e-mail w ustawieniach konta", a takich ustawień
w panelu nie było. Jedyną drogą był Django admin, do którego klient nie ma
dostępu — komunikat wysyłał go donikąd.

Testy pilnują tego, co przy tej funkcji może realnie zaszkodzić: żeby
pracownik nie przekierował powiadomień na siebie i żeby błędny adres nie
wszedł po cichu do bazy (a stamtąd w wysyłkę, jako 501 od serwera poczty).
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant

URL = "/api/accounts/firma/"


def zaloguj(tenant, rola="owner", nazwa="wl"):
    uzytkownik = CustomUser.objects.create_user(
        username=nazwa,
        email=f"{nazwa}@firma.pl",
        password="x",
        tenant=tenant,
        role=rola,
    )
    klient = APIClient()
    klient.force_authenticate(user=uzytkownik)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return klient


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Dwor Weselny", owner_email="stary@firma.pl")


@pytest.mark.django_db
class TestOdczytu:
    def test_wlasciciel_widzi_biezace_ustawienia(self, firma):
        odp = zaloguj(firma).get(URL)

        assert odp.status_code == 200
        assert odp.json() == {"name": "Dwor Weselny", "owner_email": "stary@firma.pl"}

    def test_pusty_adres_wraca_jako_pusty_napis_nie_null(self, db):
        """Formularz w panelu wiąże pole z wartością — `null` daje
        niekontrolowany input i ostrzeżenie Reacta przy pierwszym wpisaniu."""
        pusta = Tenant.objects.create(name="Bez adresu", owner_email=None)

        assert zaloguj(pusta).get(URL).json()["owner_email"] == ""


@pytest.mark.django_db
class TestZapisu:
    def test_wlasciciel_zmienia_adres_powiadomien(self, firma):
        """Sedno: to jest ta droga, której wcześniej nie było."""
        odp = zaloguj(firma).patch(URL, {"owner_email": "nowy@firma.pl"}, format="json")

        assert odp.status_code == 200
        firma.refresh_from_db()
        assert firma.owner_email == "nowy@firma.pl"

    def test_zmiana_nazwy_firmy(self, firma):
        zaloguj(firma).patch(URL, {"name": "Dwor Pod Debem"}, format="json")

        firma.refresh_from_db()
        assert firma.name == "Dwor Pod Debem"

    def test_pominiete_pole_zostaje_bez_zmian(self, firma):
        """PATCH ma zmieniać to, co przysłano — nie zerować reszty."""
        zaloguj(firma).patch(URL, {"name": "Nowa nazwa"}, format="json")

        firma.refresh_from_db()
        assert firma.owner_email == "stary@firma.pl"

    def test_pusty_adres_jest_dozwolony(self, firma):
        """Znaczy "nie powiadamiaj". Odrzucanie pustej wartości zamykałoby
        jedyną drogę wypisania się z powiadomień."""
        odp = zaloguj(firma).patch(URL, {"owner_email": ""}, format="json")

        assert odp.status_code == 200
        firma.refresh_from_db()
        assert firma.owner_email == ""


@pytest.mark.django_db
class TestWalidacji:
    @pytest.mark.parametrize(
        "zly",
        [
            "bez-malpy.pl",
            "powiadomienia@agencjasm_art.pl",  # podkreślnik — dokładnie ta awaria z produkcji
            "dwa@@razy.pl",
            "spacja w srodku@firma.pl",
        ],
    )
    def test_bledny_adres_nie_wchodzi_do_bazy(self, firma, zly):
        """Bez tego zly adres siedzi cicho do pierwszego zapytania od klienta,
        a wtedy wychodzi jako 501 od serwera poczty — czyli w najgorszym
        momencie. Podkreślnik w domenie to nie przyklad teoretyczny, tylko
        awaria, ktora realnie zatrzymala powiadomienia na produkcji."""
        odp = zaloguj(firma).patch(URL, {"owner_email": zly}, format="json")

        assert odp.status_code == 400
        firma.refresh_from_db()
        assert firma.owner_email == "stary@firma.pl"

    def test_pusta_nazwa_firmy_odrzucona(self, firma):
        """Nazwa idzie w temat maila i do widgetu — pusta zostawia klienta
        z listem od nikogo."""
        odp = zaloguj(firma).patch(URL, {"name": "   "}, format="json")

        assert odp.status_code == 400
        firma.refresh_from_db()
        assert firma.name == "Dwor Weselny"


@pytest.mark.django_db
class TestUprawnien:
    def test_pracownik_nie_przekieruje_powiadomien(self, firma):
        """Adres powiadomien decyduje o tym, kto dowiaduje sie o zapytaniach
        od klientow. Pracownik nie moze przekierowac tego strumienia na siebie
        ani po cichu go wylaczyc."""
        odp = zaloguj(firma, rola="employee", nazwa="prac").patch(
            URL, {"owner_email": "pracownik@gmail.com"}, format="json"
        )

        assert odp.status_code == 403
        firma.refresh_from_db()
        assert firma.owner_email == "stary@firma.pl"

    def test_bez_logowania_ani_slowa(self, firma):
        anonim = APIClient()
        anonim.credentials(HTTP_X_API_KEY=str(firma.api_key))

        assert anonim.get(URL).status_code in (401, 403)

    def test_wlasciciel_nie_siegnie_do_obcej_firmy(self, firma, db):
        """Widok operuje na firmie z konta, nie na niczym z zadania —
        nie ma parametru, ktorym dalo by sie wskazac cudza firme."""
        obca = Tenant.objects.create(name="Obca", owner_email="obca@firma.pl")

        odp = zaloguj(firma).patch(
            URL, {"name": "Przejete", "tenant": obca.id, "id": obca.id}, format="json"
        )

        assert odp.status_code == 200
        obca.refresh_from_db()
        assert obca.name == "Obca"
        assert obca.owner_email == "obca@firma.pl"


@pytest.mark.django_db
class TestOdpornosciUprawnienia:
    """
    IsOwner strzeze tez zapraszania i cofania zaproszen pracownikow
    (api/views/accounts.py). Niezalogowane zadanie wywracalo te widoki
    bledem 500 zamiast zwrocic odmowe: klasa siegala po request.user.role,
    a AnonymousUser tego pola nie ma. Poza zlym kodem odpowiedzi zasmiecalo
    to logi wyjatkami przy kazdym wejsciu bota z internetu.
    """

    @pytest.mark.parametrize(
        "sciezka",
        [
            "/api/accounts/firma/",
            "/api/accounts/invitations/",
        ],
    )
    def test_anonim_dostaje_odmowe_a_nie_bledu_serwera(self, firma, sciezka):
        anonim = APIClient()
        anonim.credentials(HTTP_X_API_KEY=str(firma.api_key))

        odp = anonim.get(sciezka)

        assert odp.status_code in (401, 403), f"{sciezka} zwrocilo {odp.status_code}"
