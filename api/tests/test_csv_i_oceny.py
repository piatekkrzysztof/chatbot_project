"""
F19 - poprawne CSV i integralność ocen.

Każdy przypadek odtwarza sytuację, w której eksport stawał się narzędziem
ataku na właściciela, import zostawiał bazę w połowie albo oceny dało się
ustawić z zewnątrz. Opis i wyniki na starym kodzie: docs/csv-i-oceny.md.
"""

import csv
import io

import pytest
from django.contrib.admin.sites import AdminSite
from django.http import HttpRequest
from rest_framework.test import APIClient

from chat.admin import PromptLogAdmin
from chat.models import ChatFeedback, ChatMessage, Conversation, PromptLog
from chat.zapytania import logi_klientow, rozmowy_klientow

EKSPORT = "/api/chat/export/"
IMPORT = "/api/chat/import/"


@pytest.fixture
def wlasciciel(user, tenant, subscribtion):
    user.tenant, user.role = tenant, "owner"
    user.save()
    klient = APIClient()
    klient.force_authenticate(user=user)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    # Stary kod kończył część przypadków wyjątkiem; chcemy zobaczyć kod odpowiedzi.
    klient.raise_request_exception = False
    return klient


def komorki(tresc):
    return list(csv.reader(io.StringIO(tresc.decode("utf-8").lstrip("﻿"))))


def log(tenant, prompt="Pytanie", response="Odpowiedź", **pola):
    pola.setdefault(
        "conversation", Conversation.objects.create(tenant=tenant, user_identifier="ip")
    )
    return PromptLog.objects.create(
        tenant=tenant, prompt=prompt, response=response, source="document", model="m", **pola
    )


@pytest.mark.django_db
class TestEksportu:
    @pytest.mark.parametrize(
        "wpis",
        [
            '=HYPERLINK("http://zly.example/";"Kliknij")',
            "+cmd|' /C calc'!A0",
            "-2+3",
            "@SUM(1;1)",
            "\t=1+1",
            "\r=1+1",
        ],
    )
    def test_formula_od_odwiedzajacego_nie_wykonuje_sie_w_arkuszu(self, wlasciciel, tenant, wpis):
        # Na starym kodzie komórka zaczynała się od znaku formuły.
        log(tenant, prompt=wpis)
        wiersze = komorki(wlasciciel.get(EKSPORT).content)
        assert wiersze[1][1] == "'" + wpis

    def test_zwykly_tekst_i_liczby_bez_zmian(self, wlasciciel, tenant):
        """Straż: neutralizacja dotyczy tylko początku jak formuła."""
        log(tenant, prompt="Ile kosztuje strzyżenie?", response="50 zł, a z myciem 70 zł.")
        wiersz = komorki(wlasciciel.get(EKSPORT).content)[1]
        assert wiersz[1:4] == ["Ile kosztuje strzyżenie?", "50 zł, a z myciem 70 zł.", "0"]

    def test_bom_dla_excela(self, wlasciciel, tenant):
        log(tenant, prompt="Zażółć gęślą jaźń")
        assert wlasciciel.get(EKSPORT).content.startswith(b"\xef\xbb\xbf")

    def test_wpis_po_retencji_rozmowy_nie_psuje_eksportu(self, wlasciciel, tenant):
        # Rozmowa skasowana w ramach retencji zostawia wpis z conversation=None.
        # Na starym kodzie cały eksport firmy kończył się błędem 500.
        log(tenant, prompt="Stare pytanie", conversation=None)
        odpowiedz = wlasciciel.get(EKSPORT)
        assert odpowiedz.status_code == 200
        assert komorki(odpowiedz.content)[1][:2] == ["", "Stare pytanie"]

    def test_eksport_z_panelu_administracyjnego_tez_neutralizuje(self, tenant):
        log(tenant, prompt="=1+1")
        odpowiedz = PromptLogAdmin(PromptLog, AdminSite()).export_as_csv(
            HttpRequest(), PromptLog.objects.all()
        )
        assert komorki(odpowiedz.content)[1][4] == "'=1+1"


def plik(tresc, nazwa="historia.csv"):
    dane = io.BytesIO(tresc if isinstance(tresc, bytes) else tresc.encode("utf-8"))
    dane.name = nazwa
    return dane


@pytest.mark.django_db
class TestImportu:
    def test_blad_kodowania_w_polowie_pliku_nie_zostawia_polowy(self, wlasciciel):
        # Wiersze ponad bufor dekodera (8 KB), potem bajty spoza UTF-8. Na starym
        # kodzie początek był już zapisany, a odpowiedź kończyła się błędem 500.
        poczatek = "prompt,response\n" + "".join(
            f"Pytanie numer {i},Odpowiedź numer {i}\n" for i in range(400)
        )
        odpowiedz = wlasciciel.post(
            IMPORT, {"file": plik(poczatek.encode() + b"\xff\xfe,zle\n")}, format="multipart"
        )
        assert odpowiedz.status_code == 400
        assert PromptLog.objects.count() == 0

    def test_nieprawidlowa_skladnia_to_400_i_nic_nie_zapisane(self, wlasciciel):
        # Pole ponad limit modułu csv (131 072 znaki) - na starym kodzie 500.
        tresc = "prompt,response\nPierwsze,ok\n" + "Drugie," + "x" * 140_000 + "\n"
        odpowiedz = wlasciciel.post(IMPORT, {"file": plik(tresc)}, format="multipart")
        assert odpowiedz.status_code == 400
        assert PromptLog.objects.count() == 0

    def test_brak_wymaganych_kolumn_to_blad_nie_sukces(self, wlasciciel):
        # Na starym kodzie: 201 i "imported": 0 - plik z literówką w nagłówku
        # wyglądał na udany import.
        odpowiedz = wlasciciel.post(
            IMPORT, {"file": plik("pytanie,odpowiedz\nA,B\n")}, format="multipart"
        )
        assert odpowiedz.status_code == 400
        assert "prompt" in odpowiedz.data["error"]

    def test_dwie_rozmowy_importu_nie_blokuja_kolejnych(self, wlasciciel, tenant):
        # Na starym kodzie get_or_create rzucał MultipleObjectsReturned - każdy
        # kolejny import kończył się błędem 500.
        for _ in range(2):
            Conversation.objects.create(tenant=tenant, user_identifier="imported")
        odpowiedz = wlasciciel.post(
            IMPORT, {"file": plik("prompt,response\nA,B\n")}, format="multipart"
        )
        assert odpowiedz.status_code == 201
        assert odpowiedz.data["imported"] == 1

    def test_limit_wierszy_odrzuca_caly_plik(self, wlasciciel, monkeypatch):
        monkeypatch.setattr("api.views.chat_csv.MAKS_WIERSZY_IMPORTU", 3, raising=False)
        tresc = "prompt,response\n" + "".join(f"P{i},O{i}\n" for i in range(4))
        odpowiedz = wlasciciel.post(IMPORT, {"file": plik(tresc)}, format="multipart")
        assert odpowiedz.status_code == 400
        assert PromptLog.objects.count() == 0

    def test_limit_rozmiaru_przy_odbiorze(self, wlasciciel, settings):
        settings.CSV_IMPORT_MAX_UPLOAD_BYTES = 64
        tresc = "prompt,response\n" + "Pytanie,Odpowiedź\n" * 20
        odpowiedz = wlasciciel.post(IMPORT, {"file": plik(tresc)}, format="multipart")
        assert odpowiedz.status_code == 413
        assert PromptLog.objects.count() == 0

    def test_poprawny_import(self, wlasciciel, tenant):
        # Plik z BOM, tak jak zapisuje Excel ("CSV UTF-8"). Na starym kodzie nagłówek
        # czytał się jako "﻿prompt" i import zapisywał zero wierszy z kodem 201.
        tresc = "﻿prompt,response\nCzym jest Python?,Językiem\nPuste,\nDrugie,Tak\n"
        odpowiedz = wlasciciel.post(IMPORT, {"file": plik(tresc)}, format="multipart")
        assert odpowiedz.status_code == 201
        assert odpowiedz.data["imported"] == 2
        assert set(PromptLog.objects.values_list("source", flat=True)) == {"imported"}

    def test_zaimportowana_historia_nie_jest_ruchem_klientow(self, wlasciciel, tenant):
        # Na starym kodzie import zawyżał pulpit i trafiał do eksportu jak
        # rozmowy z widgetu.
        log(tenant, prompt="Prawdziwe pytanie")
        wlasciciel.post(IMPORT, {"file": plik("prompt,response\nStare,Tak\n")}, format="multipart")
        assert list(logi_klientow(tenant).values_list("prompt", flat=True)) == ["Prawdziwe pytanie"]
        assert rozmowy_klientow(tenant).count() == 1


def wiadomosc_bota(tenant, zrodlo="widget"):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="ip", source=zrodlo)
    return ChatMessage.objects.create(conversation=rozmowa, sender="bot", message="Odpowiedź")


@pytest.mark.django_db
class TestOcenZWidgetu:
    URL = "/api/widget/feedback/"

    def ocen(self, tenant, wiadomosc, sesja, is_helpful=True):
        dane = {"message_id": wiadomosc.id, "is_helpful": is_helpful}
        if sesja is not None:
            dane["conversation_session_id"] = str(sesja)
        return APIClient().post(self.URL, dane, format="json", HTTP_X_API_KEY=str(tenant.api_key))

    def test_nie_da_sie_ocenic_cudzej_rozmowy_tej_samej_firmy(self, tenant):
        # Klucz API widgetu jest publiczny. Na starym kodzie wystarczał numer
        # wiadomości, żeby ustawić ocenę dowolnej odpowiedzi firmy.
        moja = wiadomosc_bota(tenant)
        cudza = wiadomosc_bota(tenant)
        odpowiedz = self.ocen(tenant, cudza, moja.conversation.session_id, is_helpful=False)
        assert odpowiedz.status_code == 400
        assert not ChatFeedback.objects.filter(message=cudza).exists()

    def test_ocena_bez_sesji_odrzucona(self, tenant):
        wiadomosc = wiadomosc_bota(tenant)
        assert self.ocen(tenant, wiadomosc, None).status_code == 400
        assert not ChatFeedback.objects.exists()

    def test_odmowa_nie_zdradza_istnienia_wiadomosci(self, tenant):
        cudza = wiadomosc_bota(tenant)
        zla_sesja = self.ocen(tenant, cudza, "00000000-0000-0000-0000-000000000000")
        brak = APIClient().post(
            self.URL,
            {"message_id": 999_999, "is_helpful": True},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )
        assert zla_sesja.json() == brak.json()

    def test_wlasna_rozmowa_ocenia_sie_normalnie(self, tenant):
        """Straż."""
        wiadomosc = wiadomosc_bota(tenant)
        assert self.ocen(tenant, wiadomosc, wiadomosc.conversation.session_id).status_code == 200
        assert ChatFeedback.objects.get(message=wiadomosc).is_helpful is True


@pytest.mark.django_db
class TestOcenZPanelu:
    URL = "/api/chat/feedback/"

    def test_panel_nie_nadpisuje_oceny_odwiedzajacego(self, wlasciciel, tenant):
        # Na starym kodzie członek zespołu - także w roli viewer - zmieniał
        # z panelu ocenę wystawioną przez klienta.
        wiadomosc = wiadomosc_bota(tenant)
        ChatFeedback.objects.create(message=wiadomosc, is_helpful=True)
        odpowiedz = wlasciciel.post(self.URL, {"message_id": wiadomosc.id, "is_helpful": False})
        assert odpowiedz.status_code == 400
        assert ChatFeedback.objects.get(message=wiadomosc).is_helpful is True

    def test_panel_ocenia_rozmowe_testowa(self, wlasciciel, tenant):
        """Straż."""
        wiadomosc = wiadomosc_bota(tenant, zrodlo="test")
        odpowiedz = wlasciciel.post(self.URL, {"message_id": wiadomosc.id, "is_helpful": False})
        assert odpowiedz.status_code == 200
        assert ChatFeedback.objects.get(message=wiadomosc).is_helpful is False
