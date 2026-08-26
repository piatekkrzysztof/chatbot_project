"""
Kod odmowy, po ktorym widget wie, ze ponawianie nic nie da.

Kategoria ryzyka: CICHA AWARIA po stronie odwiedzajacego. Bez tego kodu widget
traktowal wygasla subskrypcje tak samo jak chwilowy blad sieci i pokazywal
"Wystapil blad. Sprobuj ponownie." -- czyli prosil o powtorzenie czegos, co
nigdy nie zadziala, i nie dawal zadnego innego wyjscia.

Jeden kod dla wszystkich powodow celowo: rozliczenia klienta nie sa sprawa
jego odwiedzajacych. Ten test pilnuje takze tego -- ze w odpowiedzi dla
odwiedzajacego nie ma nazwy planu ani dat.
"""
from datetime import date, timedelta

import pytest
from django.urls import reverse

from accounts.middleware import KOD_CZAT_NIEDOSTEPNY
from accounts.models import Subscription, Tenant


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Rowerownia Krakowska", owner_email="szef@rowerownia.pl")


def wyslij_wiadomosc(client, firma):
    return client.post(
        reverse("widget-chat-stream"),
        data={"message": "Dzien dobry"},
        content_type="application/json",
        HTTP_X_API_KEY=str(firma.api_key),
    )


@pytest.mark.django_db
class TestKoduOdmowy:
    def test_wygasla_subskrypcja_niesie_kod(self, client, firma):
        wczoraj = date.today() - timedelta(days=1)
        Subscription.objects.create(
            tenant=firma, plan_type="start",
            start_date=wczoraj - timedelta(days=30), end_date=wczoraj,
            is_active=True,
        )

        odpowiedz = wyslij_wiadomosc(client, firma)

        assert odpowiedz.status_code == 403
        assert odpowiedz.json()["kod"] == KOD_CZAT_NIEDOSTEPNY

    def test_brak_subskrypcji_niesie_ten_sam_kod(self, firma, client):
        # Dla odwiedzajacego to ta sama sytuacja: czat nie odpowie.
        odpowiedz = wyslij_wiadomosc(client, firma)

        assert odpowiedz.status_code == 403
        assert odpowiedz.json()["kod"] == KOD_CZAT_NIEDOSTEPNY

    def test_wyczerpany_limit_niesie_ten_sam_kod(self, firma, client):
        dzisiaj = date.today()
        Subscription.objects.create(
            tenant=firma, plan_type="start",
            start_date=dzisiaj - timedelta(days=1), end_date=dzisiaj + timedelta(days=30),
            is_active=True, message_limit=10, current_message_count=10,
        )

        odpowiedz = wyslij_wiadomosc(client, firma)

        assert odpowiedz.status_code == 429
        assert odpowiedz.json()["kod"] == KOD_CZAT_NIEDOSTEPNY

    def test_odpowiedz_nie_zdradza_rozliczen_klienta(self, firma, client):
        # Odwiedzajacy sklep nie ma sie dowiadywac, ze wlascicielowi skonczyl
        # sie okres probny. To jego sprawa z nami, nie z jego klientami.
        wczoraj = date.today() - timedelta(days=1)
        Subscription.objects.create(
            tenant=firma, plan_type="start",
            start_date=wczoraj - timedelta(days=30), end_date=wczoraj,
            is_active=True,
        )

        tresc = wyslij_wiadomosc(client, firma).content.decode()

        assert "start" not in tresc.lower()
        assert str(wczoraj) not in tresc


@pytest.mark.django_db
class TestZwyklychBledow:
    def test_zly_klucz_odbija_sie_o_rozpoznanie_firmy(self, client, firma):
        """
        Zly klucz to zle wklejony snippet, nie niedostepnosc czatu.

        Widget nie ma wtedy proponowac zostawienia kontaktu -- takie zapytanie
        i tak nie trafiloby do zadnej firmy, bo nie wiadomo, do ktorej.

        Pierwsza wersja tego testu sprawdzala tylko brak pola `kod` i
        przechodzila NIEZALEZNIE od tego, co robi warstwa subskrypcji: zly
        klucz odrzuca wczesniejszy TenantMiddleware, wiec do tamtej warstwy
        zapytanie w ogole nie dociera. Test wygladal sensownie i nie pilnowal
        niczego. Teraz sprawdza konkretna odmowe, wiec da sie go zlamac.
        """
        odpowiedz = client.post(
            reverse("widget-chat-stream"),
            data={"message": "Dzien dobry"},
            content_type="application/json",
            HTTP_X_API_KEY="00000000-0000-0000-0000-000000000000",
        )

        assert odpowiedz.status_code == 401
        assert "Nieprawidłowy klucz API" in odpowiedz.json()["detail"]
        assert "kod" not in odpowiedz.json()
