"""
Powitanie nie jest luką w wiedzy.

Objaw, sprawdzony na produkcji 8 września 2026: odwiedzający pisze „cześć,
jest tam kto?", bot odpowiada ciepło — i widget od razu prosi o dane
kontaktowe. W pierwszej wymianie zdań. Ten sam wpis ląduje w raporcie luk
jako brakująca wiedza, więc właściciel dostaje list z poradą „uzupełnij bazę
wiedzy o odpowiedź na «cześć»".

Przyczyna była w jednej linijce `determine_source`: gdy wyszukiwarka nic nie
zwróciła, źródłem szło „gpt". Kiedyś nie było lepszej przesłanki. Teraz jest —
znacznik `[BRAK_ODPOWIEDZI]`, którym model MÓWI, że nie ma wiedzy.

Trzy konsumenty źródła i wszystkie trzy myliły się tak samo:
  • widget (`event.source === 'gpt'` → propozycja kontaktu),
  • raport luk (`filter(source="gpt")`),
  • wykres pokrycia w panelu (powitania zaniżały pokrycie).
"""

from unittest.mock import patch

import pytest

from accounts.models import Tenant
from api.utils.chat_engine import ZNACZNIK_BRAKU, determine_source, process_chat_message
from chat.models import (
    FAQ,
    ZRODLO_BRAK_WIEDZY,
    ZRODLO_DOKUMENT,
    ZRODLO_ROZMOWY,
    Conversation,
    PromptLog,
)
from chat.raport_luk import luki_w_wiedzy


class TestRozstrzygania:
    def test_bez_znacznika_i_bez_fragmentow_to_rozmowa(self):
        assert determine_source([], [], "Dzien dobry") == ZRODLO_ROZMOWY

    def test_znacznik_bije_wszystko(self):
        # Model powiedzial, ze nie ma wiedzy. To jest luka, niezaleznie od
        # tego, co zwrocila wyszukiwarka.
        assert determine_source([], [], "Czy robicie chrzciny?", brak_pokrycia=True) == (
            ZRODLO_BRAK_WIEDZY
        )

    def test_awaria_wyszukiwania_to_luka_a_nie_rozmowa(self):
        """
        Najważniejszy test w tym pliku.

        Pusta lista fragmentów przestała znaczyć jedno. Brak trafień to
        normalny wynik — tak wygląda „dzień dobry". Awaria pgvectora to co
        innego: pytanie mogło być prawdziwe, a bot i tak odpowiadał bez bazy
        wiedzy.

        Bez tego rozróżnienia awaria wyszukiwania zapisywałaby się jako miła
        pogawędka i znikała z raportu luk — czyli psulibyśmy monitoring
        dokładnie w chwili, w której jest potrzebny.
        """
        assert determine_source([], [], "Ile kosztuje przeglad?", wyszukiwanie_padlo=True) == (
            ZRODLO_BRAK_WIEDZY
        )


@pytest.mark.django_db
class TestCalejSciezki:
    def _firma(self):
        return Tenant.objects.create(name="Rowerownia", owner_email="x@example.com")

    @patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
    @patch("api.utils.chat_engine.get_openai_response")
    def test_powitanie_nie_prosi_o_kontakt(self, model, _fragmenty):
        """
        Widget proponuje kontakt wyłącznie przy źródle „gpt"
        (WidgetChat.tsx: `event.source === 'gpt'`). Inne źródło znaczy, że
        formularz się nie pokaże — i o to chodzi.
        """
        model.return_value = {"content": "Dzien dobry! W czym moge pomoc?", "tokens": 20}
        firma = self._firma()
        rozmowa = Conversation.objects.create(tenant=firma)

        wynik = process_chat_message(firma, rozmowa, "Czesc, jest tam kto?")

        assert wynik["source"] == ZRODLO_ROZMOWY
        assert wynik["source"] != ZRODLO_BRAK_WIEDZY

    @patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
    @patch("api.utils.chat_engine.get_openai_response")
    def test_powitanie_nie_wchodzi_do_raportu_luk(self, model, _fragmenty):
        model.return_value = {"content": "Dzien dobry!", "tokens": 20}
        firma = self._firma()
        rozmowa = Conversation.objects.create(tenant=firma)

        process_chat_message(firma, rozmowa, "Czesc, jest tam kto?")

        # Uwaga: tresc CELOWO nie jest na liscie NIE_PYTANIA w raport_luk.py.
        # Tamten filtr lapie "czesc", nie lapie "czesc, jest tam kto?" - i to
        # wlasnie dlatego rozstrzyga teraz zrodlo, a nie slownik.
        assert luki_w_wiedzy(firma) == []

    @patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
    @patch("api.utils.chat_engine.get_openai_response")
    def test_prawdziwa_luka_dalej_wchodzi_do_raportu(self, model, _fragmenty):
        """
        Druga strona. Bez tego testu zmiana dalaby sie "poprawic" tak, ze
        raport luk jest zawsze pusty - a to jest jedyna rzecz, jaka ten
        produkt mowi klientowi o jego wlasnych klientach.
        """
        model.return_value = {
            "content": f"{ZNACZNIK_BRAKU} Nie mam tej informacji.",
            "tokens": 20,
        }
        firma = self._firma()
        rozmowa = Conversation.objects.create(tenant=firma)

        process_chat_message(firma, rozmowa, "Czy organizujecie wycieczki po Bieszczadach?")

        luki = luki_w_wiedzy(firma)
        assert [p["pytanie"] for p in luki] == ["Czy organizujecie wycieczki po Bieszczadach?"]

    @patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[])
    @patch("api.utils.chat_engine.get_openai_response")
    def test_odpowiedz_z_faq_nie_jest_rozmowa(self, model, _fragmenty):
        model.return_value = {"content": "Tak, naprawiamy.", "tokens": 20}
        firma = self._firma()
        FAQ.objects.create(
            tenant=firma, question="Czy naprawiacie rowery elektryczne?", answer="Tak"
        )
        rozmowa = Conversation.objects.create(tenant=firma)

        wynik = process_chat_message(firma, rozmowa, "Czy naprawiacie rowery elektryczne?")

        assert wynik["source"] == "faq"

    @patch("api.utils.chat_engine.get_openai_response")
    def test_zrodlo_rozmowy_zapisuje_sie_w_bazie(self, model):
        # Pole ma choices, wiec nowa wartosc bez migracji przeszlaby w kodzie
        # i wywalila sie dopiero przy walidacji formularza w adminie.
        model.return_value = {"content": "Dzien dobry!", "tokens": 20}
        firma = self._firma()
        rozmowa = Conversation.objects.create(tenant=firma)

        with patch("api.utils.chat_engine.query_similar_chunks_pgvector", return_value=[]):
            process_chat_message(firma, rozmowa, "Dzien dobry")

        wpis = PromptLog.objects.filter(tenant=firma).latest("created_at")
        wpis.full_clean(exclude=["conversation"])
        assert wpis.source == ZRODLO_ROZMOWY


@pytest.mark.django_db
class TestPokryciaWPanelu:
    def test_rozmowa_ma_wlasna_kolumne_i_nie_zaniza_pokrycia(self, user, tenant, subscribtion):
        """
        Panel liczy pokrycie jako (document + faq) / (document + faq + gpt).

        Powitania wliczone do „gpt" zaniżały tę liczbę: klient widział gorsze
        pokrycie, bo odwiedzający się przywitali. Osobna kolumna zdejmuje je
        z mianownika, a zarazem nie ukrywa ich całkiem — widać, ile ruchu to
        sama grzeczność.
        """
        from rest_framework.test import APIClient

        rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="a")
        for zrodlo, ile in ((ZRODLO_DOKUMENT, 3), (ZRODLO_BRAK_WIEDZY, 1), (ZRODLO_ROZMOWY, 6)):
            for numer in range(ile):
                PromptLog.objects.create(
                    tenant=tenant,
                    conversation=rozmowa,
                    model="test",
                    prompt=f"{zrodlo}-{numer}",
                    source=zrodlo,
                    tokens=1,
                )

        user.tenant = tenant
        user.role = "owner"
        user.save()
        klient = APIClient()
        klient.force_authenticate(user=user)
        odpowiedz = klient.get("/api/analytics/", HTTP_X_API_KEY=str(tenant.api_key))

        assert odpowiedz.status_code == 200
        zrodla = odpowiedz.json()["answer_sources"]

        assert zrodla["rozmowa"] == 6, (
            "Powitania zniknely ze statystyk zamiast stanac obok nich - nie da "
            "sie wtedy zobaczyc, ile ruchu to sama grzecznosc."
        )
        assert zrodla["document"] == 3
        assert zrodla["gpt"] == 1

        # Pokrycie liczone przez panel: 3 / (3 + 0 + 1) = 75%. Przed zmiana
        # te same dane dawaly 3 / 10 = 30%, bo szesc powitan siedzialo w "gpt".
        pokrycie = zrodla["document"] + zrodla["faq"]
        assert pokrycie / (pokrycie + zrodla["gpt"]) == 0.75
