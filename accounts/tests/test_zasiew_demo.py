"""
Zasiew firmy demonstracyjnej.

Kategoria ryzyka: WITRYNA SKLEPOWA. To jest pierwsza rzecz, którą widzi ktoś
oceniający produkt. Demo, które wygląda na sprawne, a nie odpowiada z bazy
wiedzy, kosztuje wiarygodność dokładnie w tym momencie, w którym jej najbardziej
potrzeba - i nikt tego nie zgłosi, bo zwiedzający po prostu zamknie kartę.

Tak było naprawdę: na produkcji demo miało bazę wiedzy, z której nie dawało
się wyciągnąć ani jednego zdania, a bot odpowiadał wyłącznie z FAQ. Wyszło
dopiero przy pomiarze progu odległości, nie przy przeglądzie kodu.
"""

from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import OutputWrapper
from unittest.mock import MagicMock

from accounts.management.commands.zasiej_demo import DOKUMENTY_DEMO, PYTANIA_BEZ_POKRYCIA
from accounts.models import Tenant
from documents.models import Document, DocumentChunk


@pytest.fixture
def zasiane(db):
    call_command("zasiej_demo", stdout=OutputWrapper(MagicMock()))
    return Tenant.objects.get(name__contains="DEMO")


@pytest.mark.django_db
class TestBazyWiedzy:
    def test_dokumenty_maja_prawdziwa_tresc(self, zasiane):
        """
        Najważniejszy test w tym pliku.

        Wczesniej `content` byl wypelniaczem ("x" razy N). Fragmenty powstaja
        wlasnie z `content`, wiec caly potok - i zasiew, i przelicz_fragmenty -
        liczyl wektory bezsensownego tekstu. Zaden fragment nie mogl trafic
        w zadne pytanie, a demo wygladalo na dzialajace.
        """
        for dokument in Document.objects.filter(tenant=zasiane):
            tresc = dokument.content
            assert len(tresc) > 300, f"{dokument.name}: tresc zbyt krotka"
            # Wypelniacz rozpoznajemy po tym, ze sklada sie z jednego znaku.
            assert len(set(tresc.replace("\n", ""))) > 20, (
                f"{dokument.name}: tresc wyglada na wypelniacz"
            )

    def test_fragmenty_powstaja_z_tresci_dokumentu(self, zasiane):
        for dokument in Document.objects.filter(tenant=zasiane):
            for fragment in DocumentChunk.objects.filter(document=dokument):
                # Fragment musi byc kawalkiem dokumentu, a nie wymyslona
                # etykieta w rodzaju "Cennik - fragment 1", ktora stala tu
                # wczesniej i nie miala pokrycia w tresci strony.
                assert fragment.content.strip(), "pusty fragment"
                assert len(fragment.content) > 100

    def test_kazdy_dokument_ma_co_najmniej_jeden_fragment(self, zasiane):
        for dokument in Document.objects.filter(tenant=zasiane):
            assert DocumentChunk.objects.filter(document=dokument).exists(), (
                f"{dokument.name}: brak fragmentow, bot nie ma z czego odpowiadac"
            )

    def test_liczba_znakow_zgadza_sie_z_trescia(self, zasiane):
        # Panel pokazuje rozmiar bazy wiedzy. Wymyslona liczba znaczylaby,
        # ze zwiedzajacy widzi miare, ktora nie ma pokrycia w danych.
        for dokument in Document.objects.filter(tenant=zasiane):
            assert dokument.znakow_na_stronie == len(dokument.content)


@pytest.mark.django_db
class TestZeZasiewNieWolaOpenAI:
    """
    Zasiew ma działać bez klucza API - to jest jego zadeklarowana własność.
    """

    def test_zaden_dokument_nie_zleca_generowania_wektorow(self, db):
        """
        Dokument z processed=True i bez fragmentow odpala sygnal post_save,
        a ten generuje WLASNY komplet fragmentow przez OpenAI. Zasiew dokladal
        potem drugi komplet, wiec demo konczylo z dwiema kopiami tej samej
        tresci: jedna z wektorami prawdziwymi, druga z losowymi.

        Tak wygladalo demo na produkcji. Przy okazji komenda, ktora z zalozenia
        "nie wola OpenAI", wolala je po cichu przy kazdym uruchomieniu - takze
        na maszynie kogos, kto tylko chcial zobaczyc projekt.
        """
        with patch("documents.signals.enqueue") as zlecenie:
            call_command("zasiej_demo", stdout=OutputWrapper(MagicMock()))

        assert zlecenie.call_count == 0, (
            f"zasiew zlecil {zlecenie.call_count} zadan generowania wektorow"
        )

    def test_nie_powstaja_zdublowane_fragmenty(self, zasiane):
        tresci = [f.content for f in DocumentChunk.objects.filter(document__tenant=zasiane)]

        assert len(tresci) == len(set(tresci)), "ta sama tresc zapisana wiecej niz raz"


@pytest.mark.django_db
class TestLukiWBazieWiedzy:
    def test_dokumenty_nie_opisuja_pytan_bez_pokrycia(self, zasiane):
        """
        Demo ma pokazywać także lukę, nie same sukcesy.

        `PYTANIA_BEZ_POKRYCIA` to pytania, na ktore firma demo swiadomie nie
        odpowiada - panel pokazuje je jako nieodpowiedziane. Gdyby ktos dopisal
        te tematy do tresci dokumentow, ta czesc demo przestalaby cokolwiek
        pokazywac, a nikt by tego nie zauwazyl.

        Sprawdzamy slowa kluczowe, nie sens - to gruby test, ale wychwytuje
        dokladnie ten rodzaj nieuwaznej edycji.
        """
        caly_tekst = " ".join(t for _, _, t in DOKUMENTY_DEMO).lower()

        zakazane = ["uzywan", "używan", "zastępcz", "zastepcz", "odroczon"]
        znalezione = [slowo for slowo in zakazane if slowo in caly_tekst]

        assert not znalezione, (
            f"tresc demo dotyka tematow z luki wiedzy: {znalezione}. "
            f"Pytania bez pokrycia: {PYTANIA_BEZ_POKRYCIA}"
        )
