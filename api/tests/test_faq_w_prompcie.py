"""
Wpisy FAQ, których model nigdy nie widział.

Kategoria ryzyka: CICHA UTRATA WIEDZY KLIENTA (F25).

Do promptu szło `FAQ.objects.filter(tenant=...).order_by("id")[:20]`. Kolejność
po id jest stała, więc klient z dwudziestoma pięcioma wpisami miał pięć, do
których bot nie sięgał NIGDY - nie „czasem", nie „przy dużym ruchu". Zawsze.

Gorzej: ta sama lista rozstrzyga o źródle odpowiedzi
(`faq_matches_question` → `determine_source`). Pytanie odpowiadające
dwudziestemu trzeciemu wpisowi:

  1. nie dostawało go w prompcie, więc bot odmawiał,
  2. szło jako brak wiedzy firmy,
  3. lądowało w raporcie luk,
  4. i właściciel dostawał co tydzień list z poradą „uzupełnij bazę wiedzy"
     o rzecz, którą miał wpisaną.

Produkt i miara myliły się tak samo i w tę samą stronę - czyli nic tego nie
mogło pokazać.
"""

import logging
from unittest.mock import patch

import pytest

from accounts.models import Tenant
from api.utils.chat_engine import build_chat_messages, process_chat_message
from api.utils.pokrycie import (
    MAKS_FAQ_DO_PRZESZUKANIA,
    MAKS_FAQ_W_PROMPCIE,
    ZNACZNIK_BRAKU,
    wybierz_faq,
)
from chat.models import FAQ, Conversation
from chat.raport_luk import luki_w_wiedzy

pytestmark = pytest.mark.django_db

#: Pytanie i odpowiedź, które stoją DALEKO za dawnym progiem dwudziestu wpisów.
PYTANIE_SPOZA_DWUDZIESTKI = "Czy wystawiacie fakturę VAT?"
ODPOWIEDZ_SPOZA_DWUDZIESTKI = "Tak, fakturę VAT wystawiamy do siedmiu dni."


def firma_z_wieloma_faq(ile_przed=22):
    """
    Firma, u której szukany wpis jest dopiero po `ile_przed` innych.

    Wypełniacze są celowo o czymś zupełnie innym niż pytanie testowe - inaczej
    wybór „najlepiej pasujących" trafiałby w nie przypadkiem i test przechodziłby
    z niewłaściwego powodu.
    """
    firma = Tenant.objects.create(name="Rowerownia", owner_email="x@example.com")
    for numer in range(ile_przed):
        FAQ.objects.create(
            tenant=firma,
            question=f"Jak wymienić przerzutkę numer {numer}?",
            answer=f"Instrukcja numer {numer}.",
        )
    szukany = FAQ.objects.create(
        tenant=firma,
        question=PYTANIE_SPOZA_DWUDZIESTKI,
        answer=ODPOWIEDZ_SPOZA_DWUDZIESTKI,
    )
    return firma, szukany


class TestWyboruWpisow:
    def test_wpis_spoza_dwudziestki_trafia_do_promptu(self):
        """Test odtwarzający błąd: przed poprawką ten wpis nie był w prompcie."""
        firma, _szukany = firma_z_wieloma_faq()
        rozmowa = Conversation.objects.create(tenant=firma)

        with patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]):
            wiadomosci, _fragmenty, faqi, _padlo = build_chat_messages(
                firma, rozmowa, PYTANIE_SPOZA_DWUDZIESTKI
            )

        systemowa = wiadomosci[0]["content"]
        assert ODPOWIEDZ_SPOZA_DWUDZIESTKI in systemowa, (
            "Wpis FAQ odpowiadajacy na zadane pytanie nie trafil do modelu."
        )
        assert PYTANIE_SPOZA_DWUDZIESTKI in {faq.question for faq in faqi}

    def test_sufit_liczby_wpisow_dalej_obowiazuje(self):
        # Sufit jest kosztowy: kazdy wpis to tokeny przy KAZDYM pytaniu.
        # Poprawka zmienia to, KTORE wpisy przechodza, nie ile.
        firma, _szukany = firma_z_wieloma_faq(ile_przed=60)
        rozmowa = Conversation.objects.create(tenant=firma)

        with patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]):
            _wiadomosci, _fragmenty, faqi, _padlo = build_chat_messages(
                firma, rozmowa, PYTANIE_SPOZA_DWUDZIESTKI
            )

        assert len(faqi) == MAKS_FAQ_W_PROMPCIE

    def test_przy_remisie_zostaje_kolejnosc_wstawiania(self):
        """
        Pytanie niepasujące do niczego daje wszystkim ten sam wynik. Wtedy
        zachowanie ma być identyczne jak przed poprawką - pierwsze wpisy wedlug
        id - żeby zmiana nie przestawiała niczego tam, gdzie nie ma czego wybierać.
        """
        firma = Tenant.objects.create(name="Rowerownia", owner_email="x@example.com")
        wpisy = [
            FAQ.objects.create(tenant=firma, question="Aaa", answer=f"odpowiedz {numer}")
            for numer in range(5)
        ]

        wybrane = wybierz_faq(wpisy, "zupelnie inne pytanie", ile=3)

        assert [f.id for f in wybrane] == [f.id for f in wpisy[:3]]

    def test_brak_wpisow_nie_wywraca_wyboru(self):
        assert wybierz_faq([], "cokolwiek") == []


class TestZgodnosciZeZrodlem:
    """
    Prompt i decyzja o źródle muszą widzieć ten sam zbiór.

    Rozjazd między nimi znaczy, że bot odpowiada z wpisu FAQ, a system zapisuje
    to jako brak wiedzy - albo odwrotnie. Obie pomyłki są ciche.
    """

    @patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
    @patch("api.utils.chat_engine.get_openai_response")
    def test_odpowiedz_z_dalekiego_wpisu_ma_zrodlo_faq(self, model, _fragmenty):
        model.return_value = {"content": ODPOWIEDZ_SPOZA_DWUDZIESTKI, "tokens": 20}
        firma, _szukany = firma_z_wieloma_faq()
        rozmowa = Conversation.objects.create(tenant=firma)

        wynik = process_chat_message(firma, rozmowa, PYTANIE_SPOZA_DWUDZIESTKI)

        assert wynik["source"] == "faq"

    @patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
    @patch("api.utils.chat_engine.get_openai_response")
    def test_daleki_wpis_nie_laduje_w_raporcie_luk(self, model, _fragmenty):
        """
        Objaw widziany przez właściciela: list z poradą „uzupełnij bazę wiedzy"
        o pytanie, na które ma już wpisaną odpowiedź.

        Podstawiony model ZACHOWUJE SIĘ JAK PRAWDZIWY: odmawia, gdy odpowiedzi
        nie ma w tym, co dostał. Bez tego test przechodziłby także wtedy, gdy
        wpis w ogóle nie trafił do promptu.

        Czego ten test NIE pilnuje: zgodności promptu ze źródłem. Gdy prompt
        liczy z jednego zbioru, a źródło z drugiego, odpowiedź zapisuje się jako
        „rozmowa" i raport luk jest pusty tak samo - objaw znika, mechanizm
        nadal jest zepsuty. Od tego jest `test_odpowiedz_z_dalekiego_wpisu_ma_zrodlo_faq`
        i to on czerwieni się przy tej mutacji.
        """

        def odmawia_gdy_nie_dostal(wiadomosci, *args, **kwargs):
            systemowa = wiadomosci[0]["content"]
            if ODPOWIEDZ_SPOZA_DWUDZIESTKI in systemowa:
                return {"content": ODPOWIEDZ_SPOZA_DWUDZIESTKI, "tokens": 20}
            return {"content": f"{ZNACZNIK_BRAKU} Nie mam tej informacji.", "tokens": 20}

        model.side_effect = odmawia_gdy_nie_dostal
        firma, _szukany = firma_z_wieloma_faq()
        rozmowa = Conversation.objects.create(tenant=firma)

        process_chat_message(firma, rozmowa, PYTANIE_SPOZA_DWUDZIESTKI)

        assert luki_w_wiedzy(firma) == [], (
            "Pytanie, na ktore klient ma wpisana odpowiedz, trafilo do raportu luk."
        )


class TestPulapuPrzeszukiwania:
    """
    Powyżej pułapu wracamy do kolejności wstawiania - świadomie i głośno.

    Dopasowanie liczy się w Pythonie, więc gdzieś musi być granica. Granica bez
    komunikatu byłaby jednak powrotem do tego samego cichego błędu, tyle że
    przesuniętym o dwa rzędy wielkości.
    """

    def test_przekroczony_pulap_zostawia_slad_w_logu(self, caplog):
        firma = Tenant.objects.create(name="Duza", owner_email="x@example.com")
        FAQ.objects.bulk_create(
            [
                FAQ(tenant=firma, question=f"Pytanie {numer}", answer=f"Odpowiedz {numer}")
                for numer in range(MAKS_FAQ_DO_PRZESZUKANIA + 1)
            ]
        )
        rozmowa = Conversation.objects.create(tenant=firma)

        with (
            caplog.at_level(logging.WARNING, logger="api.utils.chat_engine"),
            patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]),
        ):
            build_chat_messages(firma, rozmowa, "cokolwiek")

        assert any("wpisow FAQ" in zapis.message for zapis in caplog.records), (
            "Przekroczenie pulapu przeszlo bez sladu - a powyzej niego wracaja "
            "dokladnie te skutki, ktore ta poprawka usuwa."
        )

    def test_ponizej_pulapu_log_milczy(self, caplog):
        # Ostrzezenie przy kazdym pytaniu przestaje cokolwiek znaczyc.
        firma, _szukany = firma_z_wieloma_faq()
        rozmowa = Conversation.objects.create(tenant=firma)

        with (
            caplog.at_level(logging.WARNING, logger="api.utils.chat_engine"),
            patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]),
        ):
            build_chat_messages(firma, rozmowa, "cokolwiek")

        assert not [zapis for zapis in caplog.records if "wpisow FAQ" in zapis.message]
