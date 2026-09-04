"""
Ostrzeżenie o rozmiarze bazy wiedzy.

Kategoria ryzyka: CICHY SUFIT. Wyszukiwanie spowalnia stopniowo, więc nie ma
momentu, w którym coś się psuje - jest tylko coraz dłuższe czekanie. Klient
zauważy to później niż my, a my nie zauważymy wcale, jeśli nikt nie uruchomi
komendy pomiarowej i nie porówna liczb z tabelą.

Ten plik pilnuje dwóch rzeczy naraz i obie są potrzebne: żeby alert przyszedł,
gdy klient rośnie, i żeby nie przychodził codziennie o tym samym.
"""

from unittest.mock import patch

import pytest
from django.core import mail

from accounts.models import Tenant
from accounts.rozmiar_bazy import (
    PROG_PILNY,
    PROG_UWAGI,
    ZgloszonyRozmiar,
    firmy_przy_progu,
    sprawdz_rozmiary,
)
from documents.models import Document, DocumentChunk

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def adres_alertow(settings):
    settings.EMAIL_ALERTOW = "alerty@example.com"


def firma_z_fragmentami(nazwa, ile, uzywaj=True):
    firma = Tenant.objects.create(name=nazwa, owner_email=f"{nazwa}@example.com")
    dokument = Document.objects.create(
        tenant=firma, name="Baza", content="x", processed=False, uzywaj_w_wyszukiwaniu=uzywaj
    )
    DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(document=dokument, content=f"f{i}", embedding=[0.0] * 1536)
            for i in range(ile)
        ],
        batch_size=500,
    )
    return firma


class TestKiedyMilczy:
    def test_mala_baza_nie_alarmuje(self):
        firma_z_fragmentami("Rowerownia", 300)

        assert firmy_przy_progu() == []

    def test_tuz_ponizej_progu_milczy(self):
        firma_z_fragmentami("Rowerownia", PROG_UWAGI - 1)

        assert firmy_przy_progu() == []

    def test_o_tym_samym_progu_piszemy_raz(self):
        """
        Zadanie chodzi codziennie, a baza wiedzy nie kurczy sie sama. Bez
        znacznika ta sama firma wysylalaby wiadomosc kazdego ranka i po tygodniu
        nikt by ich nie czytal - lacznie z ta, ktora bylaby o kims innym.
        """
        firma_z_fragmentami("Rowerownia", PROG_UWAGI)

        assert sprawdz_rozmiary() == 1
        assert sprawdz_rozmiary() == 0
        assert len(mail.outbox) == 1


class TestKiedyAlarmuje:
    def test_polowa_kolana_daje_uprzedzenie(self):
        firma_z_fragmentami("Rowerownia", PROG_UWAGI)

        znalezione = firmy_przy_progu()

        assert len(znalezione) == 1
        assert znalezione[0]["prog"] == PROG_UWAGI

    def test_kolano_daje_sygnal_pilny(self):
        firma_z_fragmentami("Rowerownia", PROG_PILNY)

        assert firmy_przy_progu()[0]["prog"] == PROG_PILNY

    def test_firma_ktora_przeskoczyla_oba_progi_dostaje_jedna_wiadomosc(self):
        """
        Klient, ktory wgral duzo naraz, przekracza oba progi tego samego dnia.
        Dwie wiadomosci o tym samym zdarzeniu ucza traktowac je jak szum.
        """
        firma_z_fragmentami("Rowerownia", PROG_PILNY + 100)

        znalezione = firmy_przy_progu()

        assert len(znalezione) == 1
        assert znalezione[0]["prog"] == PROG_PILNY

    def test_przekroczenie_drugiego_progu_odzywa_sie_na_nowo(self):
        # Uprzedzenie i wezwanie to dwa rozne zdarzenia. Firma, ktora rosla
        # powoli, ma uslyszec o kolanie, mimo ze o polowie juz slyszala.
        firma = firma_z_fragmentami("Rowerownia", PROG_UWAGI)
        assert sprawdz_rozmiary() == 1

        dokument = Document.objects.get(tenant=firma)
        DocumentChunk.objects.bulk_create(
            [
                DocumentChunk(document=dokument, content=f"d{i}", embedding=[0.0] * 1536)
                for i in range(PROG_PILNY - PROG_UWAGI)
            ],
            batch_size=500,
        )

        assert sprawdz_rozmiary() == 1
        assert len(mail.outbox) == 2

    def test_wiadomosc_podaje_czas_a_nie_sama_liczbe_wierszy(self):
        """
        „2 500 fragmentow" nic nie mowi komus, kto nie pamieta tabeli
        z pomiaru. Milisekundy mowia od razu, czy to juz boli.
        """
        firma_z_fragmentami("Rowerownia", PROG_UWAGI)

        sprawdz_rozmiary()
        tresc = mail.outbox[0].body

        assert "Rowerownia" in tresc
        assert "ms" in tresc
        # Odbiorca ma wiedziec, gdzie szukac decyzji, a nie tylko ze jest problem.
        assert "adr" in tresc.lower()


class TestCoLiczymy:
    def test_wylaczone_dokumenty_tez_sie_licza(self):
        """
        Wylaczony dokument nie bierze udzialu w wyszukiwaniu, wiec dzis nie
        kosztuje. Ale klient wlacza go jednym kliknieciem w panelu i wtedy
        koszt wraca - a alert przyszedlby po fakcie.
        """
        firma_z_fragmentami("Rowerownia", PROG_UWAGI, uzywaj=False)

        assert len(firmy_przy_progu()) == 1

    def test_kazda_firma_liczona_osobno(self):
        firma_z_fragmentami("Duza", PROG_UWAGI)
        firma_z_fragmentami("Mala", 100)

        znalezione = firmy_przy_progu()

        assert [w["tenant"].name for w in znalezione] == ["Duza"]


class TestNiezawodnosci:
    def test_nieudana_wysylka_nie_stawia_znacznika(self):
        firma_z_fragmentami("Rowerownia", PROG_UWAGI)

        with patch(
            "accounts.rozmiar_bazy.send_mail", side_effect=RuntimeError("SMTP nie odpowiada")
        ):
            with pytest.raises(RuntimeError):
                sprawdz_rozmiary()

        assert ZgloszonyRozmiar.objects.count() == 0
        assert sprawdz_rozmiary() == 1

    def test_zero_doreczen_bez_wyjatku_tez_jest_porazka(self):
        firma_z_fragmentami("Rowerownia", PROG_UWAGI)

        with patch("accounts.rozmiar_bazy.send_mail", return_value=0):
            with pytest.raises(RuntimeError):
                sprawdz_rozmiary()

        assert ZgloszonyRozmiar.objects.count() == 0
