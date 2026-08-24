"""
Wyciąganie treści ze strony klienta.

Zmierzone na żywej witrynie: strona główna miała 10 037 znaków widocznego
tekstu, a `trafilatura` wyciągała z niej 257 — trzy procent. Trzy podstrony
z pięciu były w bazie wiedzy praktycznie puste, a w panelu świeciły zielonym
"gotowe". Przyczyną nie były ustawienia (przełączenie tabel i favor_recall
dawało 263 znaki zamiast 257), tylko sam sposób działania biblioteki: ocenia,
co jest artykułem, a strona sprzedażowa artykułem nie jest.

Testy pilnują dwóch rzeczy naraz, bo obie da się zepsuć jedną zmianą:
że treść sekcji marketingowych przechodzi, i że nawigacja ze stopką nie.
"""
import pytest

from documents.utils.tresc_strony import bez_obudowy, wyciagnij_tresc

# Strona sprzedażowa ze znacznikami semantycznymi — tak zbudowana jest witryna
# agencji, na której robiliśmy pomiar.
SEMANTYCZNA = """
<html><body>
  <header><a href="/">Logo firmy</a></header>
  <nav><a href="/uslugi">Uslugi</a> <a href="/cennik">Cennik</a> <a href="/kontakt">Kontakt</a></nav>
  <main>
    <section><h2>Strony internetowe</h2>
      <p>Strona wizytowka z autorskim projektem od 3 900 zl, sklep e-commerce od 5 900 zl.</p></section>
    <section><h2>Opieka techniczna</h2>
      <p>Aktualizacje, kopie zapasowe i monitoring dostepnosci. Abonament od 290 zl miesiecznie.</p></section>
    <section><h2>Pozycjonowanie lokalne</h2>
      <p>Wizytowka Google, opinie i tresci lokalne. Pierwsze efekty po trzech miesiacach.</p></section>
  </main>
  <footer><p>Sm-art 2026. Polityka prywatnosci. Wszystkie prawa zastrzezone.</p></footer>
</body></html>
"""

# Ten sam układ na gotowym motywie: zero znaczników semantycznych, wszystko
# w divach z klasami. Tak wygląda większość stron małych firm.
NIESEMANTYCZNA = """
<html><body>
  <div class="site-header"><div class="logo">Logo firmy</div></div>
  <div class="navbar"><a href="/uslugi">Uslugi</a> <a href="/cennik">Cennik</a></div>
  <div id="cookie-banner">Uzywamy plikow cookie. Zaakceptuj wszystkie.</div>
  <div class="content">
    <div class="section"><h2>Strony internetowe</h2>
      <p>Strona wizytowka z autorskim projektem od 3 900 zl, sklep e-commerce od 5 900 zl.</p></div>
    <div class="section"><h2>Opieka techniczna</h2>
      <p>Aktualizacje, kopie zapasowe i monitoring dostepnosci. Abonament od 290 zl miesiecznie.</p></div>
  </div>
  <div class="site-footer">Sm-art 2026. Polityka prywatnosci.</div>
</body></html>
"""


class TestOdcinaniaObudowy:
    @pytest.mark.parametrize("html", [SEMANTYCZNA, NIESEMANTYCZNA], ids=["semantyczna", "na-divach"])
    def test_nawigacja_i_stopka_nie_wchodza(self, html):
        """
        Obudowa powtarza sie na kazdej podstronie. Wciagnieta do bazy wiedzy
        tworzy kilkanascie niemal identycznych fragmentow pasujacych "po
        trochu" do kazdego pytania — dokladnie to robila sekcja "Kontakt".
        """
        tekst = bez_obudowy(html)

        assert "Polityka prywatnosci" not in tekst
        assert "Logo firmy" not in tekst

    @pytest.mark.parametrize("html", [SEMANTYCZNA, NIESEMANTYCZNA], ids=["semantyczna", "na-divach"])
    def test_tresc_sekcji_przechodzi(self, html):
        """Druga strona tej samej monety: filtr ma odcinac obudowe, nie tresc."""
        tekst = bez_obudowy(html)

        assert "3 900 zl" in tekst
        assert "290 zl miesiecznie" in tekst

    def test_baner_zgod_wypada(self):
        assert "pliki cookie" not in bez_obudowy(NIESEMANTYCZNA).lower()

    def test_naglowki_sekcji_zostaja(self):
        """Naglowek jedzie z trescia do jednego fragmentu (documents/utils/
        fragmenty.py), wiec musi przetrwac ekstrakcje."""
        tekst = bez_obudowy(SEMANTYCZNA)

        assert "Strony internetowe" in tekst
        assert "Opieka techniczna" in tekst

    def test_struktura_wierszy_przetrwa(self):
        """Podzial na fragmenty opiera sie na akapitach. Sklejenie wszystkiego
        w jeden ciag odtworzyloby stary problem: fragment mieszajacy kilka
        uslug, z wektorem bedacym ich usrednieniem."""
        tekst = bez_obudowy(SEMANTYCZNA)

        assert "\n" in tekst
        assert "\n\n\n" not in tekst


class TestNieodcinaniaZaDuzo:
    def test_klasa_zawierajaca_slowo_obudowy_nie_kasuje_tresci(self):
        """
        Dopasowanie po CALYM czlonie klasy, nie po fragmencie. "header-title"
        to jeden wyraz, ktory nie jest na liscie — po fragmencie wylecialby
        razem z trescia sekcji.
        """
        html = """<html><body><div class="header-title"><p>Cena uslugi wynosi 3 900 zl netto
        i obejmuje projekt, wdrozenie oraz szkolenie z obslugi panelu.</p></div></body></html>"""

        assert "3 900 zl" in bez_obudowy(html)

    def test_slowo_wewnatrz_dluzszej_nazwy_nie_kasuje(self):
        html = """<html><body><div class="navigation-guide-article"><p>Przewodnik po wyborze
        uslugi: od czego zaczac, ile to trwa i ile kosztuje w praktyce.</p></div></body></html>"""

        assert "Przewodnik po wyborze" in bez_obudowy(html)


class TestWyboruDrogi:
    def test_strona_sprzedazowa_idzie_bez_obudowy(self):
        """
        Sedno naprawy. Na takiej stronie trafilatura wyciaga ulamek tresci,
        bo nie widzi w niej artykulu.
        """
        tekst = wyciagnij_tresc(SEMANTYCZNA, "https://firma.pl/").tekst

        assert "3 900 zl" in tekst
        assert "290 zl miesiecznie" in tekst
        assert "Pierwsze efekty po trzech miesiacach" in tekst

    def test_wynik_nie_jest_gorszy_niz_dotychczasowy(self):
        """Stara droga nadal startuje — bierzemy dluzszy wynik, wiec zmiana
        nie moze niczego odebrac."""
        from documents.utils.tresc_strony import przez_trafilature

        for html in (SEMANTYCZNA, NIESEMANTYCZNA):
            assert len(wyciagnij_tresc(html).tekst) >= len(przez_trafilature(html))

    def test_pusta_strona_daje_pusty_wynik(self):
        """Decyzje, co z tym zrobic, zostawiamy wywolujacemu — import rzuca
        wtedy bledem z nazwa adresu, zamiast zapisac pusty dokument."""
        assert wyciagnij_tresc("<html><body><nav>Menu</nav></body></html>").tekst == ""

    def test_za_krotka_tresc_traktujemy_jak_brak(self):
        """Ten sam prog co wczesniej. Zmiana sposobu wyciagania nie jest
        okazja, zeby po cichu przestawic takze to."""
        assert wyciagnij_tresc("<html><body><p>Krotko.</p></body></html>").tekst == ""

    def test_dlugi_artykul_przechodzi(self):
        akapit = ("Wdrozenie chatbota zaczyna sie od uporzadkowania wiedzy firmy. "
                  "Bez tego model odpowiada ogolnikami. ")
        html = f"<html><body><article><h1>Chatbot AI</h1><p>{akapit * 6}</p></article></body></html>"

        tekst = wyciagnij_tresc(html).tekst

        assert "uporzadkowania wiedzy firmy" in tekst
        assert len(tekst) > 300


@pytest.mark.django_db
class TestSciezkiImportu:
    def test_import_zapisuje_tresc_z_sekcji(self, monkeypatch):
        """Pelna sciezka: pobranie strony -> wyciagniecie -> zapis dokumentu."""
        from accounts.models import Tenant
        from documents.models import Document
        from documents.website_import import import_website_as_document

        tenant = Tenant.objects.create(name="Firma", owner_email="a@b.pl")
        monkeypatch.setattr(
            "documents.website_import.trafilatura.fetch_url", lambda url: SEMANTYCZNA
        )

        import_website_as_document(tenant, "https://firma.pl/", name="https://firma.pl/")

        dokument = Document.objects.get(tenant=tenant)
        assert "3 900 zl" in dokument.content
        assert "Polityka prywatnosci" not in dokument.content

    def test_strona_bez_tresci_konczy_bledem_z_adresem(self, monkeypatch):
        """Cicho zapisany pusty dokument wygladalby w panelu jak sukces."""
        from accounts.models import Tenant
        from documents.website_import import import_website_as_document

        tenant = Tenant.objects.create(name="Firma", owner_email="a@b.pl")
        monkeypatch.setattr(
            "documents.website_import.trafilatura.fetch_url",
            lambda url: "<html><body><nav>Menu</nav></body></html>",
        )

        with pytest.raises(ValueError, match="firma.pl"):
            import_website_as_document(tenant, "https://firma.pl/", name="x")
