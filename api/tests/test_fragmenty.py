"""
Dzielenie dokumentu na fragmenty do wyszukiwania semantycznego.

Poprzednia wersja wołała textwrap.wrap(tresc, 500) — zawijarkę wierszy, która
domyślnie zgniata białe znaki, czyli kasuje akapity i nagłówki, zanim
cokolwiek zdąży je wykorzystać. Skutek był widoczny u klienta: pytanie
o chrzciny wyciągało "fragmenty o weselach", bo w jednym 500-znakowym kawałku
naprawdę były oba tematy, a wesel było więcej, więc zdominowały wektor.

Testy pilnują trzech rzeczy, na których stoi jakość odpowiedzi bota: że sekcje
nie mieszają się w jednym fragmencie, że nagłówek jedzie razem ze swoją
treścią i że nic z dokumentu nie ginie po drodze.
"""
import pytest

from documents.utils.fragmenty import (
    MAKS_ZNAKOW,
    podziel_na_fragmenty,
    tekst_do_wektora,
)

OFERTA = """OFERTA WESELNA

Sala Debowa miesci 120 osob. Cena w sobote 4500 zl za dobe, w piatek i niedziele 3200 zl.

MENU

Menu podstawowe 180 zl od osoby: zupa, dwa dania glowne, deser, napoje bez ograniczen.

CHRZCINY I KOMUNIE

Przyjecia okolicznosciowe organizujemy w niedziele. Cena od 90 zl za osobe.

NOCLEGI

Dysponujemy 14 pokojami dla 40 gosci. Doba hotelowa 180 zl od pokoju."""


def fragment_z(fragmenty, szukane):
    """Jedyny fragment zawierający dane słowo — albo błąd, jeśli jest ich kilka."""
    trafienia = [f for f in fragmenty if szukane in f]
    assert len(trafienia) == 1, f"{szukane!r} wystepuje w {len(trafienia)} fragmentach"
    return trafienia[0]


class TestRozdzielaniaSekcji:
    def test_kazda_sekcja_ma_wlasny_fragment(self):
        """
        Sedno naprawy. Wcześniej cała ta oferta mieściła się w jednym-dwóch
        fragmentach, więc wektor "chrzcin" był w istocie wektorem wesela.
        """
        fragmenty = podziel_na_fragmenty(OFERTA)

        assert len(fragmenty) == 4

    def test_pytanie_o_chrzciny_ma_gdzie_trafic(self):
        """Fragment o chrzcinach nie może zawierac cennika wesel."""
        chrzciny = fragment_z(podziel_na_fragmenty(OFERTA), "CHRZCINY")

        assert "90 zl za osobe" in chrzciny
        assert "4500" not in chrzciny
        assert "Sala Debowa" not in chrzciny

    def test_naglowek_jedzie_ze_swoja_trescia(self):
        """
        Wcześniej "NOCLEGI" kończyło jeden fragment, a "Doba hotelowa 180 zl"
        zaczynało następny — pytanie o cenę noclegu nie trafiało dobrze
        w żaden z nich.
        """
        noclegi = fragment_z(podziel_na_fragmenty(OFERTA), "NOCLEGI")

        assert "Doba hotelowa 180 zl" in noclegi
        assert noclegi.startswith("NOCLEGI")

    def test_sam_naglowek_nie_zostaje_fragmentem(self):
        """Fragment złożony z jednego słowa nic nie wnosi, a zaśmieca wyniki."""
        fragmenty = podziel_na_fragmenty("TYTUL\n\nTresc sekcji z konkretami.")

        assert fragmenty == ["TYTUL\nTresc sekcji z konkretami."]


class TestZachowaniaTresci:
    def test_nic_nie_ginie(self):
        """Najważniejszy niewidoczny warunek: zgubiony fragment to wiedza,
        której bot nie ma, a klient jest przekonany, że wgrał."""
        polaczone = " ".join(podziel_na_fragmenty(OFERTA))

        for fakt in ["4500 zl", "180 zl od osoby", "90 zl za osobe",
                     "14 pokojami", "Doba hotelowa 180 zl"]:
            assert fakt in polaczone, f"zgubiono: {fakt}"

    def test_struktura_wierszy_przetrwa(self):
        """textwrap.wrap kasował nowe wiersze — bez nich nagłówek zlewał się
        z treścią w jeden ciąg i nie dało się ich rozpoznać."""
        fragmenty = podziel_na_fragmenty(OFERTA)

        assert any("\n" in f for f in fragmenty)

    def test_pusty_dokument_daje_pusta_liste(self):
        assert podziel_na_fragmenty("") == []
        assert podziel_na_fragmenty("   \n\n  \n") == []


class TestDlugosci:
    def test_zaden_fragment_nie_przekracza_limitu(self):
        akapit = "Zdanie o umiarkowanej dlugosci opisujace usluge. " * 8
        dokument = "\n\n".join(f"SEKCJA {i}\n\n{akapit}" for i in range(6))

        fragmenty = podziel_na_fragmenty(dokument)

        assert fragmenty
        assert all(len(f) <= MAKS_ZNAKOW + 200 for f in fragmenty), \
            [len(f) for f in fragmenty]

    def test_akapit_dluzszy_niz_limit_tniemy_po_zdaniach(self):
        """Cięcie w środku zdania gubi sens po obu stronach granicy."""
        akapit = "To jest zdanie numer {}. ".format
        dlugi = "".join(akapit(i) for i in range(200))

        fragmenty = podziel_na_fragmenty(dlugi)

        assert len(fragmenty) > 1
        # Każdy fragment kończy się pełnym zdaniem, nie urwanym słowem
        assert all(f.rstrip().endswith(".") for f in fragmenty), \
            [f[-40:] for f in fragmenty]

    def test_zdanie_dluzsze_niz_limit_nie_wywraca_podzialu(self):
        """Zdarza się w regulaminach — cięcie po słowach jest brzydkie,
        ale nie może gubić znaków ani rzucać wyjątkiem."""
        potwor = "slowo " * 500

        fragmenty = podziel_na_fragmenty(potwor)

        assert fragmenty
        assert "".join(fragmenty).count("slowo") >= 500


class TestZakladki:
    def test_sasiednie_fragmenty_zachodza_na_siebie(self):
        """
        Fakt przecięty granicą przepada bez zakładki: ani "Doba hotelowa"
        nie wie o cenie, ani cena o tym, czego dotyczy.
        """
        akapity = [f"Akapit numer {i} z trescia o dlugosci umiarkowanej. " * 6 for i in range(8)]
        dokument = "\n\n".join(akapity)

        fragmenty = podziel_na_fragmenty(dokument)

        assert len(fragmenty) > 1
        ogon_pierwszego = fragmenty[0][-60:]
        wspolne = [s for s in ogon_pierwszego.split() if s and s in fragmenty[1]]
        assert wspolne, "brak zakladki miedzy sasiednimi fragmentami"

    def test_da_sie_wylaczyc_zakladke(self):
        akapity = "\n\n".join(f"Akapit {i}. " * 40 for i in range(4))

        bez = podziel_na_fragmenty(akapity, zakladka=0)

        assert bez


class TestKontekstuWWektorze:
    def test_nazwa_dokumentu_wchodzi_do_wektora(self):
        """
        "180 zl od pokoju" znaczy co innego w cenniku hotelu niż w regulaminie
        parkingu — sam fragment tego nie niesie.
        """
        assert tekst_do_wektora("Doba 180 zl", "Cennik hotelu").startswith("Cennik hotelu")

    def test_nazwa_nie_wchodzi_do_zapisanej_tresci(self):
        """W prompcie źródło jest dodawane osobno jako [Źródło: ...], więc
        w treści fragmentu byłoby powtórzeniem zjadającym budżet tokenów."""
        fragmenty = podziel_na_fragmenty(OFERTA)

        assert not any(f.startswith("Cennik") for f in fragmenty)

    def test_brak_nazwy_nie_dokleja_pustych_wierszy(self):
        assert tekst_do_wektora("Tresc", "") == "Tresc"
        assert tekst_do_wektora("Tresc", None) == "Tresc"


@pytest.mark.django_db
class TestZapisuDoBazy:
    def _dokument(self, tresc=OFERTA):
        from accounts.models import Tenant
        from documents.models import Document

        tenant = Tenant.objects.create(name="Dwor Weselny", owner_email="w@firma.pl")
        return Document.objects.create(tenant=tenant, name="Oferta.pdf", content=tresc)

    def _udawany_klient(self, monkeypatch):
        """Model embeddingów zastąpiony liczydłem — testujemy zapis, nie OpenAI."""
        from unittest.mock import MagicMock

        import documents.utils.embedding_generator as generator

        def create(model, input):
            dane = [MagicMock(index=i, embedding=[0.01] * 1536) for i in range(len(input))]
            return MagicMock(data=dane)

        klient = MagicMock()
        klient.embeddings.create.side_effect = create
        monkeypatch.setattr(generator, "get_client", lambda tenant=None: klient)
        return klient

    def test_przeliczenie_nie_dubluje_fragmentow(self, monkeypatch):
        """
        Wcześniej fragmenty tylko przybywały. Ponowne przeliczenie po
        odświeżeniu treści ze strony klienta zostawiało oba komplety, więc bot
        odpowiadał także z wersji nieaktualnej.
        """
        from documents.models import DocumentChunk
        from documents.utils.embedding_generator import generate_embeddings_for_document

        self._udawany_klient(monkeypatch)
        dokument = self._dokument()

        generate_embeddings_for_document(dokument)
        pierwsze = DocumentChunk.objects.filter(document=dokument).count()
        generate_embeddings_for_document(dokument)

        assert DocumentChunk.objects.filter(document=dokument).count() == pierwsze

    def test_zmiana_tresci_usuwa_stare_fragmenty(self, monkeypatch):
        from documents.models import DocumentChunk
        from documents.utils.embedding_generator import generate_embeddings_for_document

        self._udawany_klient(monkeypatch)
        dokument = self._dokument()
        generate_embeddings_for_document(dokument)

        dokument.content = "NOWA OFERTA\n\nWszystko sie zmienilo, ceny takze."
        dokument.save()
        generate_embeddings_for_document(dokument)

        tresci = list(DocumentChunk.objects.filter(document=dokument).values_list("content", flat=True))
        assert all("4500" not in t for t in tresci)
        assert any("Wszystko sie zmienilo" in t for t in tresci)

    def test_wektory_lecza_partiami_a_nie_po_jednym(self, monkeypatch):
        """Wcześniej jedno żądanie HTTP na fragment: dokument na 40 fragmentów
        to 40 połączeń, a strona klienta z dwudziestoma podstronami — kilkaset."""
        from documents.utils.embedding_generator import generate_embeddings_for_document

        klient = self._udawany_klient(monkeypatch)
        generate_embeddings_for_document(self._dokument())

        assert klient.embeddings.create.call_count == 1

    def test_pusty_dokument_czysci_fragmenty(self, monkeypatch):
        from documents.models import DocumentChunk
        from documents.utils.embedding_generator import generate_embeddings_for_document

        self._udawany_klient(monkeypatch)
        dokument = self._dokument()
        generate_embeddings_for_document(dokument)

        dokument.content = ""
        dokument.save()

        assert generate_embeddings_for_document(dokument) == 0
        assert DocumentChunk.objects.filter(document=dokument).count() == 0

    def test_uzywa_klucza_openai_klienta(self, monkeypatch):
        """Klient z własnym kluczem płaci za rozmowy — powinien też za własną
        bazę wiedzy. Wcześniej ten moduł miał klienta z kluczem globalnym."""
        from documents.utils.embedding_generator import get_client

        dokument = self._dokument()
        dokument.tenant.openai_api_key = "sk-klucz-klienta"
        dokument.tenant.save()

        assert get_client(dokument.tenant).api_key == "sk-klucz-klienta"


class TestTresciSprzedazowej:
    """
    Strona sprzedazowa to nie artykul: kilkanascie krotkich linii bez kropek
    ("Umow bezplatna rozmowe", "Zobacz projekty", "→"). Heurystyka naglowkow
    uznawala 36% takich blokow za naglowek sekcji, wiec kazda linia zaczynala
    nowy fragment — z 9 280 znakow strony glownej robilo sie 58 fragmentow,
    w tym o dlugosci jednego znaku.

    Wektor jednoznakowego fragmentu nie niesie nic, a policzenie kosztuje tyle
    samo, co pelnego.
    """

    STRONA = """Twoja strona ma pracowac

wtedy, kiedy Ty nie mozesz.

Wiekszosc zapytan ginie nie dlatego, ze firma jest zla, tylko dlatego, ze nikt nie odpisal na czas. Chat odpowiada od razu, o kazdej porze.

Umow bezplatna rozmowe

albo zobacz, jak dziala moj czat

→

Certyfikowany przez:

30 minut, bez zobowiazan i bez prezentacji na 40 slajdow. Rozmawiasz ze mna, nie z handlowcem."""

    def test_krotkie_hasla_nie_staja_sie_osobnymi_fragmentami(self):
        fragmenty = podziel_na_fragmenty(self.STRONA)

        assert len(fragmenty) <= 3, [f[:40] for f in fragmenty]

    def test_zaden_fragment_nie_jest_szczatkiem(self):
        """Fragment "→" nie jest jednostka wyszukiwania."""
        fragmenty = podziel_na_fragmenty(self.STRONA)

        assert all(len(f) >= 40 for f in fragmenty), [len(f) for f in fragmenty]

    def test_nic_z_tresci_nie_ginie(self):
        """Szczatki doklejamy do sasiada, nie kasujemy."""
        polaczone = " ".join(podziel_na_fragmenty(self.STRONA))

        for fragment in ["Twoja strona ma pracowac", "Umow bezplatna rozmowe",
                         "Certyfikowany przez", "nie z handlowcem"]:
            assert fragment in polaczone, f"zgubiono: {fragment}"

    def test_krotkie_sekcje_cennika_nadal_sie_rozdzielaja(self):
        """
        Zabezpieczenie przed przesadzeniem w druga strone. Progi dobrane
        pomiarem: przy wymaganiu 90 znakow tresci pod naglowkiem sekcje
        oferty przestaja sie rozdzielac, czyli mechanizm traci sens.
        """
        assert len(podziel_na_fragmenty(OFERTA)) == 4
