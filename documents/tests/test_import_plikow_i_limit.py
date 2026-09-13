"""
F10, część 2 - pliki, które odrzucaliśmy albo czytaliśmy źle, i limit wiedzy
przy równoległych dodaniach. Opis i wyniki na starym kodzie:
docs/kompletny-import.md.
"""

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, Event
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connections, transaction
from rest_framework.test import APIClient

from documents import isolated_parser, validators
from documents.file_limits import InvalidUpload, check_text, extract_docx
from documents.models import Document
from documents.utils.tresc_strony import TrescStrony
from documents.validators import MB

# Na kodzie sprzed zmiany tej funkcji nie było. Bez zamiennika cały plik
# wywracał się przy imporcie i nie dało się sprawdzić, które przypadki
# odtwarzają błąd, a które są strażami.
zablokuj_baze_wiedzy = getattr(validators, "zablokuj_baze_wiedzy", None)

TEKST = "Cennik: strzyżenie 50 zł, koloryzacja 120 zł.\nŹródło: Łódź, ul. Świętej Anny 3."


class TestKodowaniaTekstu:
    @pytest.mark.parametrize("kodowanie", ["cp1250", "iso-8859-2", "utf-16"])
    def test_polski_tekst_poza_utf8_jest_przyjmowany_bez_przeklaman(self, kodowanie):
        # Na starym kodzie: "Plik tekstowy musi być zapisany w kodowaniu UTF-8."
        assert check_text(TEKST.encode(kodowanie)) == TEKST

    def test_windows_1250_bez_bajtow_0x80_0x9f(self):
        """ą to 0xB9 w Windows-1250 i "š" w ISO-8859-2 - rozstrzygają polskie litery."""
        tekst = "Ząb, żółw i łąka: cena 40 zł."
        assert check_text(tekst.encode("cp1250")) == tekst

    def test_utf8_bez_zmian(self):
        """Straż."""
        assert check_text(TEKST.encode("utf-8")) == TEKST
        assert check_text(b"\xef\xbb\xbf" + TEKST.encode("utf-8")) == TEKST

    def test_dane_binarne_nadal_odrzucane(self):
        """Straż: szersze kodowania nie mogą przepuścić binariów."""
        with pytest.raises(InvalidUpload):
            check_text(b"\x00\x01\x02 naglowek pliku binarnego")

    def test_bajty_bez_znaczenia_w_zadnym_kodowaniu(self):
        with pytest.raises(InvalidUpload, match="kodowania"):
            check_text(b"cena \x81\x83\x88 zl")

    def test_przez_izolowany_parser(self):
        assert isolated_parser.parse_bytes(TEKST.encode("cp1250"), "cennik.txt") == TEKST


W = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
)


def akapit(tekst, wlasciwosci=""):
    return f"<w:p>{wlasciwosci}<w:r><w:t>{tekst}</w:t></w:r></w:p>"


def wiersz(*komorki):
    return "<w:tr>" + "".join(f"<w:tc>{akapit(k)}</w:tc>" for k in komorki) + "</w:tr>"


def docx(tresc):
    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as archiwum:
        archiwum.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archiwum.writestr(
            "word/document.xml", f"<w:document {W}><w:body>{tresc}</w:body></w:document>"
        )
    return bufor.getvalue()


CENNIK_W_TABELI = "<w:tbl>" + wiersz("Usługa", "Cena") + wiersz("Strzyżenie", "50 zł") + "</w:tbl>"


class TestTekstuDocx:
    def test_wiersz_tabeli_trzyma_usluge_z_cena(self):
        # Na starym kodzie: "Usługa\nCena\nStrzyżenie\n50 zł".
        tekst = extract_docx(docx(akapit("Oferta") + CENNIK_W_TABELI))
        assert "Usługa | Cena" in tekst
        assert "Strzyżenie | 50 zł" in tekst

    def test_pole_tekstowe_tylko_raz(self):
        # Na starym kodzie tekst pola tekstowego występował dwa razy.
        pole = (
            '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wps:txbx>'
            f"<w:txbxContent>{akapit('Promocja: druga wizyta -20%')}</w:txbxContent>"
            "</wps:txbx></w:drawing></mc:Choice><mc:Fallback><w:pict><v:textbox>"
            f"<w:txbxContent>{akapit('Promocja: druga wizyta -20%')}</w:txbxContent>"
            "</v:textbox></w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>"
        )
        assert extract_docx(docx(akapit("Oferta") + pole)).count("Promocja") == 1

    def test_pozycje_tabulatorow_nie_dopisuja_znakow(self):
        tabulatory = '<w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
        tekst = extract_docx(docx(akapit("Oferta") + akapit("Cennik", tabulatory)))
        assert tekst == "Oferta\nCennik"

    def test_wiersz_w_kontrolce_tresci(self):
        tabela = (
            "<w:tbl><w:sdt><w:sdtContent>"
            + wiersz("Koloryzacja", "120 zł")
            + "</w:sdtContent></w:sdt></w:tbl>"
        )
        assert "Koloryzacja | 120 zł" in extract_docx(docx(tabela))

    def test_przez_izolowany_parser(self):
        tekst = isolated_parser.parse_bytes(docx(CENNIK_W_TABELI), "cennik.docx")
        assert "Strzyżenie | 50 zł" in tekst


def rownolegle(funkcja, argumenty):
    def uruchom(argument):
        close_old_connections()
        try:
            return funkcja(argument)
        except Exception as blad:
            return blad
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(argumenty)) as pula:
        return list(pula.map(uruchom, argumenty))


@pytest.fixture
def jednoczesny_pomiar(monkeypatch):
    """
    Oba dodania mierzą bazę, zanim którekolwiek zapisze - dokładnie ten przeplot,
    który daje przekroczenie. Bramka czeka na drugi wątek najwyżej 1,5 s: przy
    działającej blokadzie drugi wątek stoi na blokadzie, bramka się rozpada,
    a pierwszy kończy zapis przed pomiarem drugiego.
    """
    oryginal = validators.rozmiar_bazy_wiedzy
    bramka = Barrier(2)

    def z_bramka(tenant):
        wynik = oryginal(tenant)
        try:
            bramka.wait(timeout=1.5)
        except BrokenBarrierError:
            pass
        return wynik

    monkeypatch.setattr(validators, "rozmiar_bazy_wiedzy", z_bramka)
    return oryginal


def plan_start(subskrypcja):
    subskrypcja.plan_type = "start"
    subskrypcja.message_limit = 100
    subskrypcja.save()


@pytest.mark.django_db(transaction=True)
class TestLimituPrzyRownoleglychDodaniach:
    """Plan Start: 5 MB. Każde dodanie 3 MB mieści się samo, dwa razem już nie."""

    def test_dwa_uploady_naraz(self, user, tenant, subscribtion, jednoczesny_pomiar, mocker):
        plan_start(subscribtion)
        user.tenant, user.role = tenant, "owner"
        user.save()
        mocker.patch("api.views.documents.parse_document", return_value="x" * (3 * MB))

        def wgraj(nazwa):
            klient = APIClient()
            klient.force_authenticate(user=user)
            klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
            plik = SimpleUploadedFile(nazwa, b"%PDF-1.4", content_type="application/pdf")
            return klient.post("/api/documents-upload/", {"file": plik}, format="multipart")

        odpowiedzi = rownolegle(wgraj, ["a.pdf", "b.pdf"])

        assert sorted(o.status_code for o in odpowiedzi) == [201, 400]
        assert jednoczesny_pomiar(tenant) <= 5 * MB

    def test_dwie_podstrony_naraz(self, tenant, subscribtion, jednoczesny_pomiar):
        from documents.website_import import import_website_as_document

        plan_start(subscribtion)
        with patch(
            "documents.website_import.fetch_text_from_url",
            return_value=TrescStrony("x" * (3 * MB), 3 * MB),
        ):
            rownolegle(
                lambda url: import_website_as_document(tenant, url, name=url),
                ["https://firma.pl/a", "https://firma.pl/b"],
            )

        assert Document.objects.filter(tenant=tenant).count() == 1
        assert jednoczesny_pomiar(tenant) <= 5 * MB

    def test_dwa_odczyty_plikow_w_tle_naraz(self, tenant, subscribtion, jednoczesny_pomiar):
        from documents.tasks import extract_text_from_document

        plan_start(subscribtion)
        dokumenty = [
            Document.objects.create(
                tenant=tenant, name=nazwa, file=SimpleUploadedFile(nazwa, b"tresc")
            ).id
            for nazwa in ("a.txt", "b.txt")
        ]
        with patch("documents.tasks.extract_text", return_value="x" * (3 * MB)):
            rownolegle(extract_text_from_document, dokumenty)

        assert jednoczesny_pomiar(tenant) <= 5 * MB
        bledy = Document.objects.filter(tenant=tenant).exclude(processing_error="")
        assert bledy.count() == 1
        assert "limit bazy wiedzy" in bledy.get().processing_error

    def test_blokada_wiedzy_nie_wstrzymuje_czatu(self, tenant, subscribtion):
        """
        Straż wyboru blokady. Rezerwacja wiadomości blokuje wiersz firmy;
        gdyby limit wiedzy blokował ten sam wiersz, rozmowy w widżecie stałyby
        przez cały upload.
        """
        from accounts.message_quota import reserve_message

        plan_start(subscribtion)
        trzyma, zwolnij = Event(), Event()

        def trzymaj_blokade(_):
            with transaction.atomic():
                zablokuj_baze_wiedzy(tenant)
                trzyma.set()
                assert zwolnij.wait(10)

        with ThreadPoolExecutor(max_workers=2) as pula:
            blokada = pula.submit(rownolegle, trzymaj_blokade, [None])
            try:
                assert trzyma.wait(10)
                czat = pula.submit(rownolegle, lambda _: reserve_message(tenant), [None])
                wynik = czat.result(timeout=5)[0]
                assert not isinstance(wynik, Exception), wynik
            finally:
                zwolnij.set()
            blokada.result(timeout=10)

    def test_blokada_poza_transakcja_to_blad_programisty(self, tenant):
        with pytest.raises(RuntimeError):
            zablokuj_baze_wiedzy(tenant)


@pytest.mark.django_db(transaction=True)
class TestZleceniaPoZatwierdzeniu:
    def test_zlecenie_dopiero_po_zatwierdzeniu(self, tenant):
        # Na starym kodzie zlecenie szło w chwili zapisu, przed zatwierdzeniem:
        # worker mógł nie znaleźć dokumentu i zostawić go bez fragmentów.
        with patch("documents.signals.enqueue") as zlecenie:
            with transaction.atomic():
                Document.objects.create(tenant=tenant, name="c", content="tresc", processed=True)
                assert zlecenie.call_count == 0
            assert zlecenie.call_count == 1

    def test_wycofany_zapis_nie_zleca_niczego(self, tenant):
        with patch("documents.signals.enqueue") as zlecenie:
            with pytest.raises(RuntimeError), transaction.atomic():
                Document.objects.create(tenant=tenant, name="c", content="tresc", processed=True)
                raise RuntimeError("wycofanie")
        assert zlecenie.call_count == 0
