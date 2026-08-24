"""
Cykliczne odświeżanie treści ze stron klientów.

Cennik obiecuje odświeżanie co 7 dni (Grow) i codziennie (Pro), zegar chodził,
zadanie się wykonywało — i nie zmieniało niczego. W crawl_and_import_website_source
stało `continue` dla każdego adresu, który był już w bazie, więc bot odpowiadał
z wersji pobranej przy pierwszym imporcie. Klient zmieniał ceny na stronie,
a bot dalej podawał stare.

Testy pilnują trzech rzeczy: że odświeżenie faktycznie podmienia treść, że nie
mnoży kopii tej samej podstrony i że strona bez zmian nie kosztuje przeliczania
wektorów bez powodu.
"""
from unittest.mock import patch

import pytest

from accounts.models import Subscription, Tenant
from documents.utils.tresc_strony import TrescStrony
from documents.models import Document, DocumentChunk, WebsiteSource
from documents.website_import import import_website_as_document

ADRES = "https://dworweselny.pl/oferta"
STARA = "OFERTA\n\nSala na 120 osob. Cena w sobote 4500 zl za dobe."
NOWA = "OFERTA\n\nSala na 120 osob. Cena w sobote 5200 zl za dobe."


@pytest.fixture
def firma(db):
    from datetime import date, timedelta

    tenant = Tenant.objects.create(name="Dwor Weselny", owner_email="w@firma.pl")
    Subscription.objects.create(
        tenant=tenant, plan_type="pro", is_active=True,
        message_limit=25000, current_message_count=0,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


def pobierz(tresc):
    """Podmienia samo ściąganie strony — reszta ścieżki jest prawdziwa."""
    return patch("documents.website_import.fetch_text_from_url",
                 return_value=TrescStrony(tresc, len(tresc) * 2))


@pytest.mark.django_db
class TestOdswiezania:
    def test_zmieniona_strona_podmienia_tresc(self, firma):
        """Sedno naprawy: to jest ta zmiana, ktorej wczesniej nie bylo."""
        with pobierz(STARA):
            import_website_as_document(firma, ADRES, name=ADRES)
        with pobierz(NOWA):
            import_website_as_document(firma, ADRES, name=ADRES)

        dokument = Document.objects.get(tenant=firma, source_url=ADRES)
        assert "5200" in dokument.content
        assert "4500" not in dokument.content

    def test_odswiezenie_nie_mnozy_kopii_podstrony(self, firma):
        """Gdyby import dalej zakladal nowy dokument, klient planu Pro mialby
        po miesiacu trzydziesci kopii kazdej podstrony — zjadalyby limit bazy
        wiedzy i wypychaly trafne fragmenty z wynikow wyszukiwania."""
        for tresc in (STARA, NOWA, NOWA + " Aktualizacja."):
            with pobierz(tresc):
                import_website_as_document(firma, ADRES, name=ADRES)

        assert Document.objects.filter(tenant=firma, source_url=ADRES).count() == 1

    def test_strona_bez_zmian_nie_przelicza_wektorow(self, firma):
        """Przeliczanie fragmentow co dobe bez powodu kosztuje u klienta Pro
        tyle samo, co realne odswiezenie, a niczego nie wnosi."""
        with pobierz(STARA):
            import_website_as_document(firma, ADRES, name=ADRES)

        with pobierz(STARA), patch("documents.website_import.enqueue") as zlecenie:
            import_website_as_document(firma, ADRES, name=ADRES)

        assert not zlecenie.called

    def test_zmiana_tresci_zleca_przeliczenie(self, firma):
        with pobierz(STARA):
            import_website_as_document(firma, ADRES, name=ADRES)

        with pobierz(NOWA), patch("documents.website_import.enqueue") as zlecenie:
            import_website_as_document(firma, ADRES, name=ADRES)

        assert zlecenie.called

    def test_stare_fragmenty_znikaja_razem_ze_stara_trescia(self, firma, monkeypatch):
        """Bez tego bot odpowiada z obu wersji naraz — takze z nieaktualnej."""
        from unittest.mock import MagicMock

        import documents.tasks as zadania
        import documents.utils.embedding_generator as generator

        klient = MagicMock()
        klient.embeddings.create.side_effect = lambda model, input: MagicMock(
            data=[MagicMock(index=i, embedding=[0.01] * 1536) for i in range(len(input))]
        )
        monkeypatch.setattr(generator, "get_client", lambda tenant=None: klient)

        # conftest wycisza .delay na zadaniach dokumentow, zeby testy nie liczyly
        # wektorow. Ten test sprawdza wlasnie ten fragment sciezki, wiec
        # przywracamy wykonanie — z udawanym modelem embeddingow, wiec nadal
        # bez ruchu na zewnatrz.
        monkeypatch.setattr(
            "documents.tasks.generate_embeddings_for_document.delay",
            lambda document_id: zadania.generate_embeddings_for_document(document_id),
        )

        with pobierz(STARA):
            import_website_as_document(firma, ADRES, name=ADRES)
        with pobierz(NOWA):
            import_website_as_document(firma, ADRES, name=ADRES)

        dokument = Document.objects.get(tenant=firma, source_url=ADRES)
        tresci = list(DocumentChunk.objects.filter(document=dokument).values_list("content", flat=True))
        assert tresci, "dokument zostal bez fragmentow"
        assert any("5200" in t for t in tresci)
        assert all("4500" not in t for t in tresci)

    def test_rozpoznanie_po_adresie_nie_po_nazwie(self, firma):
        """Nazwe klient moze zmienic w panelu; adres jest tym, co pobieramy."""
        with pobierz(STARA):
            dokument = import_website_as_document(firma, ADRES, name="Nasza oferta")
        dokument.name = "Zupelnie inna nazwa"
        dokument.save()

        with pobierz(NOWA):
            import_website_as_document(firma, ADRES, name=ADRES)

        assert Document.objects.filter(tenant=firma, source_url=ADRES).count() == 1


@pytest.mark.django_db
class TestLimituPrzyOdswiezaniu:
    def test_odswiezenie_nie_liczy_obu_wersji_naraz(self, firma):
        """
        Licznik bazy wiedzy bral wczesniej stara i nowa wersje jednoczesnie,
        wiec klient blisko limitu nie moglby odswiezyc wlasnej strony — mimo ze
        po odswiezeniu zajmuje ona mniej wiecej tyle samo miejsca.
        """
        from documents.validators import limit_bazy_wiedzy_mb

        limit_znakow = limit_bazy_wiedzy_mb(firma) * 1024 * 1024
        duza = "x" * int(limit_znakow * 0.95)

        with pobierz(duza):
            import_website_as_document(firma, ADRES, name=ADRES)

        # Druga wersja tej samej wielkosci: razem przekroczylaby limit,
        # osobno miesci sie z zapasem
        with pobierz("y" * int(limit_znakow * 0.95)):
            import_website_as_document(firma, ADRES, name=ADRES)

        dokument = Document.objects.get(tenant=firma, source_url=ADRES)
        assert dokument.content.startswith("y")


@pytest.mark.django_db
class TestZadaniaCyklicznego:
    def test_zadanie_nie_pomija_juz_znanych_podstron(self, firma):
        """
        Wczesniej stalo tu `continue` dla adresow obecnych w bazie — czyli po
        pierwszym imporcie zadanie cykliczne nie robilo nic.
        """
        from documents.tasks import crawl_and_import_website_source

        zrodlo = WebsiteSource.objects.create(
            tenant=firma, url="https://dworweselny.pl/", name="Strona"
        )
        with pobierz(STARA):
            import_website_as_document(firma, "https://dworweselny.pl/oferta", name="https://dworweselny.pl/oferta")

        with patch("documents.tasks.sitemap_search", return_value=["https://dworweselny.pl/oferta"]), \
             pobierz(NOWA):
            crawl_and_import_website_source(zrodlo.id)

        dokument = Document.objects.get(tenant=firma, source_url="https://dworweselny.pl/oferta")
        assert "5200" in dokument.content

    def test_awaria_jednej_podstrony_nie_przerywa_reszty(self, firma):
        """Bez tego blad na trzeciej z dwudziestu podstron zostawia baze wiedzy
        w polowie odswiezona, bez sladu, ze cos poszlo nie tak."""
        from documents.tasks import crawl_and_import_website_source

        zrodlo = WebsiteSource.objects.create(
            tenant=firma, url="https://dworweselny.pl/", name="Strona"
        )
        adresy = ["https://dworweselny.pl/a", "https://dworweselny.pl/b", "https://dworweselny.pl/c"]

        def czasem_pada(url):
            if url.endswith("/b"):
                raise ValueError("strona nieosiagalna")
            tresc = f"SEKCJA\n\nTresc podstrony {url}."
            return TrescStrony(tresc, len(tresc) * 2)

        with patch("documents.tasks.sitemap_search", return_value=adresy), \
             patch("documents.website_import.fetch_text_from_url", side_effect=czasem_pada):
            crawl_and_import_website_source(zrodlo.id)

        pobrane = set(Document.objects.filter(tenant=firma).values_list("source_url", flat=True))
        assert pobrane == {"https://dworweselny.pl/a", "https://dworweselny.pl/c"}

    def test_udane_pobranie_zostawia_znacznik(self, firma):
        from documents.tasks import crawl_and_import_website_source

        zrodlo = WebsiteSource.objects.create(
            tenant=firma, url="https://dworweselny.pl/", name="Strona"
        )
        with patch("documents.tasks.sitemap_search", return_value=["https://dworweselny.pl/a"]), \
             pobierz(STARA):
            crawl_and_import_website_source(zrodlo.id)

        zrodlo.refresh_from_db()
        assert zrodlo.last_crawled_at is not None
        assert zrodlo.last_error == ""
