"""
Sufit kosztu pojedynczej wiadomości.

Prompt rósł bez ograniczenia: opis firmy, regulamin, do dwudziestu wpisów FAQ,
pięć fragmentów dokumentów i dziesięć wiadomości historii. Klient z obszernym
regulaminem generował prompt kosztujący wielokrotnie więcej niż sama odpowiedź,
a płacimy za każdy token wejściowy przy każdej wiadomości. Odpowiedź nie miała
z kolei żadnego ograniczenia długości.

Szacujemy znakami, bez tiktoken — uzasadnienie i kalibracja w api/utils/tokens.py.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from api.utils.tokens import (
    ZNAKI_NA_TOKEN,
    oszacuj_tokeny,
    oszacuj_tokeny_wiadomosci,
    przytnij_do_budzetu,
)


class TestSzacowania:
    def test_pusty_tekst_to_zero(self):
        assert oszacuj_tokeny("") == 0
        assert oszacuj_tokeny(None) == 0

    def test_szacunek_zawyza_a_nie_zanizza(self):
        """
        Dzielnik 2,5 leży poniżej najgorszego zmierzonego przypadku (polski,
        2,83 znaku na token), więc szacunek musi wychodzić wyżej niż prawda.
        Zaniżenie oznaczałoby przekroczenie budżetu, czyli rachunek wyższy
        od zakładanego.
        """
        tekst = "Jakie macie godziny otwarcia w soboty?" * 10
        realne_gorne_ograniczenie = len(tekst) / 2.83

        assert oszacuj_tokeny(tekst) >= realne_gorne_ograniczenie

    def test_narzut_rosnie_z_liczba_wiadomosci(self):
        jedna = [{"role": "user", "content": "test"}]
        trzy = [{"role": "user", "content": "test"}] * 3

        assert oszacuj_tokeny_wiadomosci(trzy) > oszacuj_tokeny_wiadomosci(jedna) * 2


class TestPrzycinania:
    def zbuduj(self, historia=6, dlugosc_systemu=100):
        wiadomosci = [{"role": "system", "content": "S" * dlugosc_systemu}]
        for i in range(historia):
            wiadomosci.append({"role": "user", "content": f"stare pytanie {i}"})
            wiadomosci.append({"role": "assistant", "content": f"stara odpowiedź {i}"})
        wiadomosci.append({"role": "user", "content": "bieżące pytanie"})
        return wiadomosci

    def test_bez_potrzeby_nic_nie_rusza(self):
        wiadomosci = self.zbuduj()

        assert przytnij_do_budzetu(wiadomosci, 10_000) == wiadomosci

    def test_miesci_sie_w_budzecie(self):
        wynik = przytnij_do_budzetu(self.zbuduj(historia=20), 200)

        assert oszacuj_tokeny_wiadomosci(wynik) <= 200

    def test_najpierw_ginie_najstarsza_historia(self):
        """
        Kolejność poświęcania jest celowa: bot traci pamięć dawnych zdań, ale
        wciąż rozumie bieżące pytanie i zna zasady zachowania.
        """
        wynik = przytnij_do_budzetu(self.zbuduj(historia=20), 300)
        tresci = [w["content"] for w in wynik]

        assert "stare pytanie 0" not in tresci
        assert wynik[-1]["content"] == "bieżące pytanie"
        assert wynik[0]["role"] == "system"

    def test_prompt_systemowy_i_pytanie_przezywaja_skrajny_budzet(self):
        """Nawet absurdalnie ciasny budżet nie może zostawić modelu bez pytania."""
        wynik = przytnij_do_budzetu(self.zbuduj(historia=20, dlugosc_systemu=5000), 50)

        assert wynik[0]["role"] == "system"
        assert wynik[-1]["content"] == "bieżące pytanie"

    def test_wiedza_ginie_dopiero_po_historii(self):
        """
        Prompt systemowy skracamy od dołu — tam siedzą dokumenty i regulamin,
        a na górze zakaz zmyślania, który musi przetrwać.
        """
        system = "ZASADY: nie zmyślaj." + ("\nRegulamin: " + "x" * 4000)
        wiadomosci = [
            {"role": "system", "content": system},
            {"role": "user", "content": "stare"},
            {"role": "assistant", "content": "stara odpowiedź"},
            {"role": "user", "content": "bieżące pytanie"},
        ]

        wynik = przytnij_do_budzetu(wiadomosci, 300)

        assert wynik[0]["content"].startswith("ZASADY: nie zmyślaj.")
        assert len(wynik[0]["content"]) < len(system)
        # Skracanie promptu systemowego też musi zmieścić się w budżecie —
        # wcześniej wychodziło dokładnie o jeden token za dużo, bo szacunek
        # zaokrągla w górę, a wyliczenie limitu znaków tego nie uwzględniało
        assert oszacuj_tokeny_wiadomosci(wynik) <= 300

    @pytest.mark.parametrize("budzet", [50, 137, 300, 1000, 6000])
    def test_dowolny_budzet_jest_dotrzymany(self, budzet):
        """
        Test na wiele budżetów, bo błąd o jeden ujawniał się tylko wtedy, gdy
        wchodził krok drugi — przy budżetach mieszczących całą historię
        przycinanie kończyło się wcześniej i problem był niewidoczny.
        """
        wiadomosci = [
            {"role": "system", "content": "ZASADY.\n" + "x" * 20000},
            {"role": "user", "content": "stare pytanie"},
            {"role": "assistant", "content": "stara odpowiedź"},
            {"role": "user", "content": "bieżące pytanie"},
        ]

        assert oszacuj_tokeny_wiadomosci(przytnij_do_budzetu(wiadomosci, budzet)) <= budzet

    def test_pusta_lista_nie_wywraca(self):
        assert przytnij_do_budzetu([], 100) == []

    def test_nie_mutuje_wejscia(self):
        wiadomosci = self.zbuduj(historia=20)
        kopia = [dict(w) for w in wiadomosci]

        przytnij_do_budzetu(wiadomosci, 100)

        assert wiadomosci == kopia


@pytest.mark.django_db
class TestLimituDlugosciPytania:
    def test_zbyt_dlugie_pytanie_odrzucone(self, tenant, subscribtion):
        response = APIClient().post(
            "/api/widget/chat/",
            {
                "message": "a" * 5000,
                "conversation_session_id": "11111111-1111-1111-1111-111111111111",
            },
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )

        assert response.status_code == 400

    @override_settings(MAX_WIADOMOSC_ZNAKOW=2000)
    def test_normalne_pytanie_przechodzi(self, tenant, subscribtion, mocker):
        mocker.patch(
            "api.utils.chat_engine.get_openai_response",
            return_value={"content": "Czynne 9-17.", "tokens": 10},
        )

        response = APIClient().post(
            "/api/widget/chat/",
            {
                "message": "Jakie macie godziny otwarcia?",
                "conversation_session_id": "22222222-2222-2222-2222-222222222222",
            },
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )

        assert response.status_code == 200
