"""
Ślad po odmowach obsługi widgetu.

Kategoria ryzyka: CICHA AWARIA. To jest bezpośrednia odpowiedź na zdanie
z raportu incydentu 26.08.2026: „We cannot count what we did not log". Widget
milczał u klienta przez dobę i do dziś nie wiadomo, ilu odwiedzających
dostało wtedy komunikat o błędzie.

Najważniejsze w tym pliku nie jest to, że licznik się podbija, tylko że
odmowa dalej DZIAŁA, gdy zapis się nie uda - narzędzie do wykrywania awarii
nie może samo być awarią.
"""

from unittest.mock import patch

import pytest
from django.utils import timezone

from accounts.models import Subscription, Tenant
from accounts.odmowy import PowodOdmowy, ZliczenieOdmow, zapisz_odmowe

URL_CZATU = "/api/widget/chat/"


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia", owner_email="szef@rowerownia.pl")


@pytest.fixture
def subskrypcja_wygasla(firma):
    """Dokładnie sytuacja z 26 sierpnia: okres próbny skończył się wczoraj."""
    dzis = timezone.localdate()
    return Subscription.objects.create(
        tenant=firma,
        plan_type="start",
        start_date=dzis - timezone.timedelta(days=14),
        end_date=dzis - timezone.timedelta(days=1),
        is_active=True,
        billing_cycle_start=dzis - timezone.timedelta(days=14),
    )


@pytest.mark.django_db
class TestZapisu:
    def test_pierwsza_odmowa_zaklada_wiersz(self, firma):
        zapisz_odmowe(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)

        wiersz = ZliczenieOdmow.objects.get()
        assert wiersz.tenant == firma
        assert wiersz.liczba == 1
        assert wiersz.dzien == timezone.localdate()
        assert wiersz.zgloszone is False

    def test_kolejne_odmowy_podbijaja_ten_sam_wiersz(self, firma):
        # Sedno decyzji projektowej: zliczenia, nie zdarzenia. Widget na
        # ruchliwej stronie z wygasla subskrypcja zebralby dziesiatki tysiecy
        # wierszy dziennie - i to akurat wtedy, gdy baza ma najmniej powodow,
        # zeby puchnac.
        for _ in range(5):
            zapisz_odmowe(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)

        assert ZliczenieOdmow.objects.count() == 1
        assert ZliczenieOdmow.objects.get().liczba == 5

    def test_rozne_powody_licza_sie_osobno(self, firma):
        zapisz_odmowe(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)
        zapisz_odmowe(firma, PowodOdmowy.LIMIT_WIADOMOSCI)

        assert ZliczenieOdmow.objects.count() == 2

    def test_odmowa_bez_firmy_tez_sie_zapisuje(self, db):
        # Nieznany klucz API nie ma czego przypisac, ale mowi o czyms realnym:
        # o zle wklejonym fragmencie na czyjejs stronie albo o kims, kto
        # obmacuje nasze API. Wyrzucenie tych odmow zgubiloby jedyny slad.
        zapisz_odmowe(None, PowodOdmowy.ZLY_KLUCZ)

        wiersz = ZliczenieOdmow.objects.get()
        assert wiersz.tenant is None
        assert wiersz.liczba == 1

    def test_godzina_ostatniej_odmowy_sie_przesuwa(self, firma):
        zapisz_odmowe(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)
        pierwszy = ZliczenieOdmow.objects.get()
        pierwsza_godzina = pierwszy.pierwsza

        zapisz_odmowe(firma, PowodOdmowy.SUBSKRYPCJA_WYGASLA)
        drugi = ZliczenieOdmow.objects.get()

        # Poczatek zostaje, koniec sie przesuwa - bez tego wiadomo, ze awaria
        # trwala, ale nie wiadomo, od ktorej godziny.
        assert drugi.pierwsza == pierwsza_godzina
        assert drugi.ostatnia >= drugi.pierwsza


@pytest.mark.django_db
class TestSciezkiZadania:
    """Odmowa musi działać niezależnie od tego, czy zapis się powiódł."""

    def test_wygasla_subskrypcja_odmawia_i_zostawia_slad(self, client, firma, subskrypcja_wygasla):
        odpowiedz = client.post(
            URL_CZATU,
            {"message": "Czy macie rowery gorskie?"},
            content_type="application/json",
            HTTP_X_API_KEY=str(firma.api_key),
        )

        assert odpowiedz.status_code == 403
        assert odpowiedz.json()["kod"] == "czat_niedostepny"

        wiersz = ZliczenieOdmow.objects.get()
        assert wiersz.tenant == firma
        assert wiersz.powod == PowodOdmowy.SUBSKRYPCJA_WYGASLA
        assert wiersz.liczba == 1

    def test_nieznany_klucz_zapisuje_sie_bez_firmy(self, db, client):
        odpowiedz = client.post(
            URL_CZATU,
            {"message": "test"},
            content_type="application/json",
            HTTP_X_API_KEY="00000000-0000-0000-0000-000000000000",
        )

        assert odpowiedz.status_code == 401
        wiersz = ZliczenieOdmow.objects.get()
        assert wiersz.tenant is None
        assert wiersz.powod == PowodOdmowy.ZLY_KLUCZ

    def test_awaria_zapisu_nie_psuje_odmowy(self, client, firma, subskrypcja_wygasla):
        """
        Najważniejszy test w tym pliku.

        Licznik jest narzędziem do wykrywania awarii. Gdyby jego własna usterka
        - przeciążona baza, wyczerpane połączenia - zamieniała odmowę 403
        w błąd 500, dołożylibyśmy systemowi nowy sposób psucia się dokładnie
        w chwili, gdy jest mu najciężej.
        """
        with patch(
            "accounts.middleware.zapisz_odmowe",
            side_effect=RuntimeError("baza nie odpowiada"),
        ):
            odpowiedz = client.post(
                URL_CZATU,
                {"message": "test"},
                content_type="application/json",
                HTTP_X_API_KEY=str(firma.api_key),
            )

        # Odwiedzajacy dostaje normalna odmowe, nie awarie serwera.
        assert odpowiedz.status_code == 403
        assert odpowiedz.json()["kod"] == "czat_niedostepny"
        assert ZliczenieOdmow.objects.count() == 0

    def test_dzialajaca_subskrypcja_nie_zapisuje_niczego(self, client, firma):
        dzis = timezone.localdate()
        Subscription.objects.create(
            tenant=firma,
            plan_type="start",
            start_date=dzis - timezone.timedelta(days=1),
            end_date=dzis + timezone.timedelta(days=30),
            is_active=True,
            billing_cycle_start=dzis,
        )

        client.post(
            URL_CZATU,
            {"message": "test"},
            content_type="application/json",
            HTTP_X_API_KEY=str(firma.api_key),
        )

        # Licznik odmow ma liczyc odmowy. Gdyby rosl przy normalnym ruchu,
        # kazdy alert bylby falszywy i po tygodniu nikt by ich nie czytal.
        assert ZliczenieOdmow.objects.count() == 0
