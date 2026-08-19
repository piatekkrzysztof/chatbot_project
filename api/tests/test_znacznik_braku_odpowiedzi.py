"""
Rozpoznanie „bot nie umiał pomóc".

Wcześniej decydowała niepustość wyników wyszukiwania: skoro cokolwiek się
znalazło, źródłem był "document". Ale wyszukiwarka wektorowa zwraca fragmenty
NAJBLIŻSZE, nie trafne — pytanie o chrzciny w firmie od wesel wyciągało cztery
fragmenty o weselach. Bot uczciwie odmawiał, a mimo to szło to jako odpowiedź
opartą o dokumenty: widget nie proponował kontaktu, zapytanie nie powstawało
i właściciel nie dowiadywał się o niczym.

Teraz mówi to sam model, znacznikiem na początku odpowiedzi. Znacznik jest
elementem protokołu, nie treścią — nie ma prawa dotrzeć do odwiedzającego.
"""
from unittest.mock import patch

import pytest

from accounts.models import Tenant
from api.utils.chat_engine import (
    ZNACZNIK_BRAKU,
    ObcinaczZnacznika,
    determine_source,
    stream_chat_message,
)
from chat.models import Conversation


def przepusc(kawalki):
    """Przepuszcza listę fragmentów przez obcinacz, tak jak robi to strumień."""
    obcinacz = ObcinaczZnacznika()
    wyszlo = "".join(obcinacz.podaj(k) for k in kawalki) + obcinacz.zakoncz()
    return wyszlo, obcinacz.brak_pokrycia


class TestObcinacza:
    def test_znacznik_w_jednym_kawalku(self):
        wyszlo, brak = przepusc([f"{ZNACZNIK_BRAKU} Nie mam tej informacji."])

        assert wyszlo == "Nie mam tej informacji."
        assert brak is True

    def test_znacznik_rozbity_miedzy_tokeny(self):
        """Model oddaje tekst po kilka znaków i nie ma żadnej gwarancji, że
        znacznik trafi w jeden token. Gdyby obcinacz patrzył tylko na pierwszy
        fragment, znacznik pokazałby się odwiedzającemu w oknie czatu."""
        wyszlo, brak = przepusc(["[BRAK", "_ODPO", "WIED", "ZI]", " Nie wiem."])

        assert wyszlo == "Nie wiem."
        assert brak is True

    @pytest.mark.parametrize("podzial", [1, 2, 3, 5, 7, 11])
    def test_zaden_podzial_nie_przepuszcza_znacznika(self, podzial):
        """Wprost: przy każdym rozmiarze tokenu w oknie czatu ma nie być
        nawiasu kwadratowego z protokołu."""
        pelna = f"{ZNACZNIK_BRAKU} Niestety nie posiadam takich informacji."
        kawalki = [pelna[i:i + podzial] for i in range(0, len(pelna), podzial)]
        wyszlo, brak = przepusc(kawalki)

        assert "BRAK_ODPOWIEDZI" not in wyszlo
        assert wyszlo == "Niestety nie posiadam takich informacji."
        assert brak is True

    def test_zwykla_odpowiedz_przechodzi_bez_zmian(self):
        wyszlo, brak = przepusc(["Przegląd ", "podstawowy ", "kosztuje 120 zł."])

        assert wyszlo == "Przegląd podstawowy kosztuje 120 zł."
        assert brak is False

    def test_odpowiedz_krotsza_niz_znacznik_nie_przepada(self):
        """Bufor wstrzymuje początek, dopóki nie wiadomo, czy to znacznik.
        „Tak." nigdy nie osiąga jego długości — bez domknięcia zniknęłoby."""
        wyszlo, brak = przepusc(["Tak."])

        assert wyszlo == "Tak."
        assert brak is False

    def test_poczatek_podobny_do_znacznika_nie_znika(self):
        """Wstrzymanie musi być odwracalne: tekst zaczynający się nawiasem
        kwadratowym, ale nie znacznikiem, ma przejść w całości."""
        wyszlo, brak = przepusc(["[BRA", "WO] to nazwa naszego lokalu."])

        assert wyszlo == "[BRAWO] to nazwa naszego lokalu."
        assert brak is False


class TestZrodla:
    def test_znacznik_bije_wyniki_wyszukiwania(self):
        """Sedno naprawy: cztery znalezione fragmenty i mimo to odmowa."""
        assert determine_source(
            chunks=["cokolwiek", "cokolwiek", "cokolwiek", "cokolwiek"],
            faqs=[], message_text="Czy organizujecie chrzciny?",
            brak_pokrycia=True,
        ) == "gpt"

    def test_bez_znacznika_dokumenty_liczą_się_jak_wcześniej(self):
        assert determine_source(
            chunks=["fragment"], faqs=[], message_text="Ile kosztuje sala?",
            brak_pokrycia=False,
        ) == "document"


class FragmentUdawany:
    """Fragment dokumentu — tyle, ile czyta z niego silnik czatu."""

    def __init__(self, nazwa="Oferta wesela.pdf"):
        self.document = type("Dokument", (), {"name": nazwa, "source_url": ""})()
        self.content = "treść"


class StrumienUdawany:
    """Minimalna imitacja odpowiedzi strumieniowej OpenAI."""

    def __init__(self, kawalki):
        self.kawalki = kawalki

    def __iter__(self):
        for kawalek in self.kawalki:
            yield type("Zdarzenie", (), {
                "usage": None,
                "choices": [type("Wybor", (), {
                    "delta": type("Delta", (), {"content": kawalek})()
                })()],
            })()


@pytest.mark.django_db
class TestSciezkiStrumieniowej:
    def _rozmowa(self):
        tenant = Tenant.objects.create(name="Dwór Weselny", owner_email="w@firma.pl")
        return tenant, Conversation.objects.create(tenant=tenant, user_identifier="gosc")

    def _przebieg(self, kawalki):
        tenant, rozmowa = self._rozmowa()
        with patch("api.utils.chat_engine.get_client") as klient, \
             patch("api.utils.chat_engine.build_chat_messages",
                   return_value=([], [FragmentUdawany()], [])):
            klient.return_value.chat.completions.create.return_value = StrumienUdawany(kawalki)
            return list(stream_chat_message(tenant, rozmowa, "Czy robicie chrzciny?"))

    def test_odmowa_konczy_sie_zrodlem_gpt(self):
        """To decyduje, czy widget zaproponuje kontakt — czyli czy zapytanie
        w ogóle powstanie i czy właściciel dostanie maila."""
        zdarzenia = self._przebieg([ZNACZNIK_BRAKU, " Nie organizujemy chrzcin."])
        koniec = [z for z in zdarzenia if '"done"' in z][0]

        assert '"source": "gpt"' in koniec

    def test_znacznik_nie_wychodzi_w_zadnym_zdarzeniu(self):
        zdarzenia = self._przebieg([ZNACZNIK_BRAKU, " Nie organizujemy chrzcin."])

        assert not any("BRAK_ODPOWIEDZI" in z for z in zdarzenia)

    def test_zapisana_wiadomosc_tez_jest_bez_znacznika(self):
        """Znacznik w bazie wyszedłby potem w panelu rozmów i w mailu
        z zapytaniem — tam też jest śmieciem."""
        from chat.models import ChatMessage

        self._przebieg([ZNACZNIK_BRAKU, " Nie organizujemy chrzcin."])
        odpowiedz = ChatMessage.objects.filter(sender="bot").latest("id")

        assert odpowiedz.message == "Nie organizujemy chrzcin."

    def test_pod_odmowa_nie_ma_zrodel(self):
        """Na screenie od klienta pod „nie posiadam informacji" wisiały cztery
        dokumenty — podpis pod czymś, czego nie ma."""
        zdarzenia = self._przebieg([ZNACZNIK_BRAKU, " Nie organizujemy chrzcin."])
        koniec = [z for z in zdarzenia if '"done"' in z][0]

        assert '"sources": []' in koniec

    def test_pod_realna_odpowiedzia_zrodla_zostaja(self):
        zdarzenia = self._przebieg(["Sala mieści 120 osób."])
        koniec = [z for z in zdarzenia if '"done"' in z][0]

        assert "Oferta wesela.pdf" in koniec
