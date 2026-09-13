"""
F10 - kompletny import wiedzy ze strony klienta.

Każdy przypadek odtwarza sytuację, w której bot po cichu dostawał za mało
wiedzy albo śmieci zamiast wiedzy, a panel pokazywał "gotowe". Opis
i wyniki na starym kodzie: docs/kompletny-import.md.
"""

import io
import random
import zipfile
from unittest.mock import Mock, patch

import pytest
from reportlab.pdfgen import canvas

from accounts.models import Subscription, Tenant
from documents import safe_http, sitemaps, website_import
from documents.models import Document, WebsiteSource
from documents.safe_http import FetchError, FetchLimitExceeded, Page
from documents.utils.tresc_strony import TrescStrony

ROOT = "https://example.com/"
ADRES = "https://example.com/cennik"
STARA = "CENNIK\n\nStrzyzenie damskie 90 zl, koloryzacja od 180 zl, modelowanie 60 zl."
NOWA = "CENNIK\n\nStrzyzenie damskie 95 zl, koloryzacja od 190 zl, modelowanie 65 zl."
CENNIK = [
    "Cennik salonu Aurora",
    "Strzyzenie damskie 90 zl, strzyzenie meskie 50 zl.",
    "Koloryzacja od 180 zl, balayage od 350 zl.",
    "Modelowanie 60 zl, zabieg regeneracyjny 120 zl.",
]
TEKST_CENNIKA = " ".join(CENNIK)

# Błąd pojedynczej za dużej odpowiedzi. Na kodzie sprzed zmiany takiej klasy
# nie było - fetch_page rzucał wtedy ogólny FetchLimitExceeded z tym samym
# komunikatem, więc to jest wierne odtworzenie tamtej sytuacji.
ZaDuzaOdpowiedz = getattr(safe_http, "ResponseTooLarge", FetchLimitExceeded)


def obraz_png():
    from PIL import Image

    losowe = random.Random(7)
    pikseli = bytes(losowe.getrandbits(8) for _ in range(120 * 120 * 3))
    bufor = io.BytesIO()
    Image.frombytes("RGB", (120, 120), pikseli).save(bufor, "PNG")
    return bufor.getvalue()


def plik_pdf():
    bufor = io.BytesIO()
    pdf = canvas.Canvas(bufor)
    for numer, wiersz in enumerate(CENNIK):
        pdf.drawString(72, 750 - numer * 20, wiersz)
    pdf.showPage()
    pdf.save()
    return bufor.getvalue()


def plik_docx():
    akapity = "".join(f"<w:p><w:r><w:t>{wiersz}</w:t></w:r></w:p>" for wiersz in CENNIK)
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as archiwum:
        archiwum.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archiwum.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{akapity}</w:body></w:document>",
        )
    return bufor.getvalue()


def podstaw_strone(monkeypatch, body, content_type, url=ADRES):
    monkeypatch.setattr(website_import, "fetch_page", lambda adres: Page(url, body, content_type))


class TestTypuTresci:
    """Pobieranie nie sprawdzało typu odpowiedzi - wszystko szło przez ekstrakcję HTML."""

    def test_obraz_nie_trafia_do_wiedzy(self, monkeypatch):
        # Na starym kodzie: 120x120 PNG dawał kilkadziesiąt tysięcy znaków
        # zdekodowanych bajtów, zapisywanych jako treść i liczonych w embeddingach.
        podstaw_strone(monkeypatch, obraz_png(), "image/png", ROOT + "galeria/1.png")
        with pytest.raises(ValueError, match="typ treści"):
            website_import.fetch_text_from_url(ROOT + "galeria/1.png")

    def test_obraz_bez_naglowka_typu_tez_nie(self, monkeypatch):
        podstaw_strone(monkeypatch, obraz_png(), "", ROOT + "obraz?id=3")
        with pytest.raises(ValueError, match="typ treści"):
            website_import.fetch_text_from_url(ROOT + "obraz?id=3")

    def test_pdf_ze_strony_czytany_jak_plik(self, monkeypatch):
        # Na starym kodzie do wiedzy trafiała składnia PDF: "%PDF-1.3 ... obj".
        podstaw_strone(monkeypatch, plik_pdf(), "application/pdf", ROOT + "cennik.pdf")
        wynik = website_import.fetch_text_from_url(ROOT + "cennik.pdf")
        assert "Koloryzacja od 180 zl" in wynik.tekst
        assert "%PDF" not in wynik.tekst

    @pytest.mark.parametrize("content_type", ["", "application/octet-stream"])
    def test_pdf_bez_wlasciwego_naglowka_rozpoznany_po_zawartosci(self, monkeypatch, content_type):
        podstaw_strone(monkeypatch, plik_pdf(), content_type, ROOT + "pobierz?plik=cennik")
        wynik = website_import.fetch_text_from_url(ROOT + "pobierz?plik=cennik")
        assert "Koloryzacja od 180 zl" in wynik.tekst

    def test_docx_ze_strony_czytany_jak_plik(self, monkeypatch):
        podstaw_strone(
            monkeypatch,
            plik_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ROOT + "regulamin.docx",
        )
        wynik = website_import.fetch_text_from_url(ROOT + "regulamin.docx")
        assert "Modelowanie 60 zl" in wynik.tekst
        assert "word/document.xml" not in wynik.tekst

    def test_zwykly_tekst_ze_strony(self, monkeypatch):
        podstaw_strone(
            monkeypatch, TEKST_CENNIKA.encode(), "text/plain; charset=utf-8", ROOT + "cennik.txt"
        )
        assert website_import.fetch_text_from_url(ROOT + "cennik.txt").tekst == TEKST_CENNIKA

    @pytest.mark.parametrize("content_type", ["text/html; charset=utf-8", ""])
    def test_strona_html_bez_zmian(self, monkeypatch, content_type):
        """Straż: serwery bez nagłówka typu dalej traktujemy jak HTML."""
        html = f"<html><body><main><p>{TEKST_CENNIKA}</p></main></body></html>".encode()
        podstaw_strone(monkeypatch, html, content_type)
        assert "Koloryzacja od 180 zl" in website_import.fetch_text_from_url(ADRES).tekst


@pytest.fixture
def firma(db):
    from datetime import date, timedelta

    tenant = Tenant.objects.create(name="Salon Aurora", owner_email="a@firma.pl")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="pro",
        is_active=True,
        message_limit=25000,
        current_message_count=0,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


@pytest.mark.django_db
class TestImportuDoBazy:
    def test_obraz_nie_nadpisuje_istniejacej_tresci(self, firma, monkeypatch):
        dokument = Document.objects.create(
            tenant=firma, source="website", source_url=ADRES, name=ADRES, content=STARA
        )
        podstaw_strone(monkeypatch, obraz_png(), "image/png")
        with pytest.raises(ValueError):
            website_import.import_website_as_document(firma, ADRES, name=ADRES)
        dokument.refresh_from_db()
        assert dokument.content == STARA

    def test_pusta_strona_nie_nadpisuje_istniejacej_tresci(self, firma, monkeypatch):
        """
        Straż, zielona także na starym kodzie. Opis F17 twierdził, że pusta
        strona nadpisuje treść - nieprawda, pobranie poniżej progu treści
        kończy się błędem przed zapisem. Test pilnuje, żeby tak zostało.
        """
        dokument = Document.objects.create(
            tenant=firma, source="website", source_url=ADRES, name=ADRES, content=STARA
        )
        podstaw_strone(monkeypatch, b"<html><body><p>Wkrotce</p></body></html>", "text/html")
        with pytest.raises(ValueError):
            website_import.import_website_as_document(firma, ADRES, name=ADRES)
        dokument.refresh_from_db()
        assert dokument.content == STARA


class TestWyszukiwaniaPodstron:
    def test_linki_do_obrazow_nie_zajmuja_miejsc_podstron(self, monkeypatch):
        # Galeria z trzydziestoma zdjęciami przed linkiem do oferty. Na starym
        # kodzie limit dwudziestu adresów wypełniały zdjęcia, a oferta nie
        # trafiała nawet do kolejki.
        galeria = "".join(f'<a href="/galeria/{i}.jpg">Zdjecie</a>' for i in range(30))
        glowna = f'{galeria}<a href="/oferta">Oferta</a>'.encode()

        def pobierz(url):
            if url.endswith(".jpg"):
                return Page(url, obraz_png(), "image/jpeg")
            return Page(url, glowna if url == ROOT else b"<p>Oferta</p>", "text/html")

        fetch = Mock(side_effect=pobierz)
        monkeypatch.setattr(website_import, "fetch_page", fetch)
        znalezione = website_import.discover_links_recursively(ROOT)
        assert ROOT + "oferta" in znalezione
        assert not any(call.args[0].endswith(".jpg") for call in fetch.call_args_list)

    def test_jeden_za_duzy_plik_nie_przerywa_wyszukiwania(self, monkeypatch):
        # Na starym kodzie przekroczenie rozmiaru jednej odpowiedzi było tym
        # samym błędem co wyczerpany budżet, więc przerywało całe pobieranie
        # źródła i klient nie dostawał żadnej podstrony.
        glowna = b'<a href="/cennik.pdf">Cennik</a><a href="/kontakt">Kontakt</a>'

        def pobierz(url):
            if url.endswith(".pdf"):
                raise ZaDuzaOdpowiedz("Strona przekracza limit rozmiaru.")
            return Page(url, glowna if url == ROOT else b"<p>Kontakt</p>", "text/html")

        monkeypatch.setattr(website_import, "fetch_page", Mock(side_effect=pobierz))
        assert ROOT + "kontakt" in website_import.discover_links_recursively(ROOT)

    def test_wyczerpany_budzet_nadal_przerywa(self, monkeypatch):
        """Straż: tylko pojedyncza odpowiedź jest pomijana, budżet źródła nie."""
        glowna = b'<a href="/kontakt">Kontakt</a>'

        def pobierz(url):
            if url == ROOT:
                return Page(url, glowna, "text/html")
            raise FetchLimitExceeded("Przekroczono limit żądań dla jednego źródła WWW.")

        monkeypatch.setattr(website_import, "fetch_page", Mock(side_effect=pobierz))
        with pytest.raises(FetchLimitExceeded):
            website_import.discover_links_recursively(ROOT)


def mapa(kind, urls):
    entry = "sitemap" if kind == "sitemapindex" else "url"
    wpisy = "".join(f"<{entry}><loc>{url}</loc></{entry}>" for url in urls)
    return f'<{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{wpisy}</{kind}>'.encode()


def podstaw_mapy(monkeypatch, odpowiedzi):
    def pobierz(url):
        if url not in odpowiedzi:
            raise FetchError("HTTP 404")
        wartosc = odpowiedzi[url]
        if isinstance(wartosc, Exception):
            raise wartosc
        return Page(url, wartosc)

    fetch = Mock(side_effect=pobierz)
    monkeypatch.setattr(sitemaps, "fetch_page", fetch)
    return fetch


STRONY_STALE = [ROOT, ROOT + "oferta/", ROOT + "cennik/", ROOT + "kontakt/", ROOT + "o-nas/"]


class TestMapyStrony:
    def test_wordpress_yoast_strony_przed_wpisami(self, monkeypatch):
        # Yoast wymienia mapę wpisów przed mapą stron. Na starym kodzie
        # dwadzieścia wpisów blogowych wyczerpywało limit, zanim import doszedł
        # do cennika i kontaktu.
        podstaw_mapy(
            monkeypatch,
            {
                ROOT + "sitemap.xml": mapa(
                    "sitemapindex",
                    [
                        ROOT + "post-sitemap.xml",
                        ROOT + "page-sitemap.xml",
                        ROOT + "category-sitemap.xml",
                    ],
                ),
                ROOT + "post-sitemap.xml": mapa("urlset", [ROOT + f"wpis-{i}/" for i in range(30)]),
                ROOT + "page-sitemap.xml": mapa("urlset", STRONY_STALE),
                ROOT + "category-sitemap.xml": mapa(
                    "urlset", [ROOT + f"category/k-{i}/" for i in range(10)]
                ),
            },
        )
        wynik = sitemaps.sitemap_search(ROOT)
        assert set(STRONY_STALE) <= set(wynik)
        assert len(wynik) == 20
        assert not any("/category/" in adres for adres in wynik)

    def test_wordpress_bez_wtyczki_mapa_stron_poza_limitem_plikow(self, monkeypatch):
        # Mapa stron jest piątą z pięciu w indeksie, a limit to pięć plików
        # łącznie z samym indeksem. Na starym kodzie nigdy jej nie pobierano.
        mapy = [
            ROOT + "wp-sitemap-posts-post-1.xml",
            ROOT + "wp-sitemap-taxonomies-category-1.xml",
            ROOT + "wp-sitemap-taxonomies-post_tag-1.xml",
            ROOT + "wp-sitemap-users-1.xml",
            ROOT + "wp-sitemap-posts-page-1.xml",
        ]
        odpowiedzi = {ROOT + "sitemap.xml": mapa("sitemapindex", mapy)}
        odpowiedzi[mapy[0]] = mapa("urlset", [ROOT + f"{i}/wpis/" for i in range(40)])
        odpowiedzi[mapy[1]] = mapa("urlset", [ROOT + f"category/k-{i}/" for i in range(10)])
        odpowiedzi[mapy[2]] = mapa("urlset", [ROOT + f"tag/t-{i}/" for i in range(10)])
        odpowiedzi[mapy[3]] = mapa("urlset", [ROOT + "author/admin/"])
        odpowiedzi[mapy[4]] = mapa("urlset", STRONY_STALE)
        fetch = podstaw_mapy(monkeypatch, odpowiedzi)

        assert set(STRONY_STALE) <= set(sitemaps.sitemap_search(ROOT))
        assert fetch.call_count <= 6  # robots + najwyżej pięć plików map, jak dotąd

    def test_strony_stale_maja_pierwszenstwo_nie_tylko_rowny_udzial(self, monkeypatch):
        # Piętnaście stron stałych za mapą trzydziestu wpisów. Równy podział
        # dałby stronom tylko dziesięć miejsc; mają dostać wszystkie piętnaście.
        strony = [ROOT + f"strona-{i}/" for i in range(15)]
        podstaw_mapy(
            monkeypatch,
            {
                ROOT + "sitemap.xml": mapa(
                    "sitemapindex", [ROOT + "post-sitemap.xml", ROOT + "page-sitemap.xml"]
                ),
                ROOT + "post-sitemap.xml": mapa("urlset", [ROOT + f"wpis-{i}/" for i in range(30)]),
                ROOT + "page-sitemap.xml": mapa("urlset", strony),
            },
        )
        wynik = sitemaps.sitemap_search(ROOT)
        assert wynik[:15] == strony
        assert len(wynik) == 20

    def test_mapy_z_rowna_waga_dziela_limit(self, monkeypatch):
        """Sklep: produkty i blog bez podpowiedzi w nazwie - żadna mapa nie bierze całości."""
        podstaw_mapy(
            monkeypatch,
            {
                ROOT + "sitemap.xml": mapa(
                    "sitemapindex", [ROOT + "sitemap_products_1.xml", ROOT + "sitemap_blogs_1.xml"]
                ),
                ROOT + "sitemap_products_1.xml": mapa(
                    "urlset", [ROOT + f"products/p-{i}" for i in range(50)]
                ),
                ROOT + "sitemap_blogs_1.xml": mapa(
                    "urlset", [ROOT + f"blogs/news/w-{i}" for i in range(50)]
                ),
            },
        )
        wynik = sitemaps.sitemap_search(ROOT)
        assert len(wynik) == 20
        assert sum("/products/" in adres for adres in wynik) == 10

    def test_za_duza_mapa_nie_przerywa_pobierania(self, monkeypatch):
        # Sklep z tysiącami produktów ma mapę ponad limit rozmiaru. Na starym
        # kodzie przerywało to całe pobieranie źródła, zamiast przejść do
        # wyszukiwania podstron po linkach.
        podstaw_mapy(
            monkeypatch,
            {ROOT + "sitemap.xml": ZaDuzaOdpowiedz("Strona przekracza limit rozmiaru.")},
        )
        assert sitemaps.sitemap_search(ROOT) == []


def pobierz_tresc(tresc):
    return patch(
        "documents.website_import.fetch_text_from_url",
        return_value=TrescStrony(tresc, len(tresc) * 2),
    )


@pytest.mark.django_db
class TestZadaniaPobierania:
    def test_adres_podany_przez_klienta_jest_zawsze_pobierany(self, firma):
        # Klient dodaje konkretną podstronę z cennikiem. Mapa strony ma więcej
        # niż dwadzieścia wpisów i tej podstrony nie ma wśród pierwszych -
        # na starym kodzie cennik nie trafiał do wiedzy nigdy.
        from documents.tasks import crawl_and_import_website_source

        zrodlo = WebsiteSource.objects.create(tenant=firma, url="https://firma.pl/cennik")
        wpisy = [f"https://firma.pl/wpis-{i}" for i in range(25)]
        with patch("documents.tasks.sitemap_search", return_value=wpisy), pobierz_tresc(NOWA):
            crawl_and_import_website_source(zrodlo.id)

        adresy = set(Document.objects.filter(tenant=firma).values_list("source_url", flat=True))
        assert "https://firma.pl/cennik" in adresy
        assert len(adresy) == 20

    @pytest.mark.parametrize(
        "zapisany,adres_zrodla,z_mapy",
        [
            # Strona główna pobrana kiedyś po linkach (pisownia źródła), dziś
            # strona ma mapę z ukośnikiem. Na starym kodzie powstawał drugi
            # dokument z tą samą treścią, a pierwszy zostawał na zawsze.
            ("https://firma.pl", "https://firma.pl", "https://firma.pl/"),
            # Odwrotnie: dokument z mapy, źródło bez ukośnika.
            ("https://firma.pl/", "https://firma.pl", "https://firma.pl/"),
        ],
    )
    def test_ta_sama_podstrona_w_innej_pisowni_nie_tworzy_kopii(
        self, firma, zapisany, adres_zrodla, z_mapy
    ):
        from documents.tasks import crawl_and_import_website_source

        Document.objects.create(
            tenant=firma, source="website", source_url=zapisany, name=zapisany, content=STARA
        )
        zrodlo = WebsiteSource.objects.create(tenant=firma, url=adres_zrodla)
        with patch("documents.tasks.sitemap_search", return_value=[z_mapy]), pobierz_tresc(NOWA):
            crawl_and_import_website_source(zrodlo.id)

        dokumenty = Document.objects.filter(tenant=firma)
        assert dokumenty.count() == 1
        assert dokumenty.get().content == NOWA
