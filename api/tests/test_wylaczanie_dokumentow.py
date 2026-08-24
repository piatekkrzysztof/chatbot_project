"""
Wyłączanie dokumentu z wyszukiwania.

Powstało z pomiaru na produkcji. Sekcja "Kontakt / Porozmawiajmy o właściwym
rozwiązaniu" ze strony agencji była najbliższym trafieniem dla sześciu
z jedenastu zmierzonych pytań — o chrzciny, kontenery z Chin, pogodę
w Wałbrzychu i pralki. Nie niesie żadnego faktu, więc leży "średnio blisko"
wszystkiego i zajmuje miejsce w piątce wyników także przy pytaniach, na które
klient ma prawdziwą odpowiedź.

Progiem odległości tego nie da się załatwić: taki fragment bywa bliżej niż
prawdziwe trafienia. Decyzję zostawiamy człowiekowi, bo tylko on wie, czy
"/kontakt" to pusta zachęta, czy strona z godzinami otwarcia i adresem.
"""
import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant
from documents.models import Document, DocumentChunk
from documents.utils.tresc_strony import TrescStrony
from rag.engine import query_similar_chunks_pgvector

WYMIAR = 1536


def wektor(x):
    v = [0.0] * WYMIAR
    v[0] = x
    return v


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Sm-art", owner_email="a@b.pl")


def dokument(tenant, nazwa, odleglosc, **kw):
    dok = Document.objects.create(tenant=tenant, name=nazwa, content="tresc", processed=True, **kw)
    DocumentChunk.objects.create(document=dok, content=f"FRAGMENT {nazwa}", embedding=wektor(odleglosc))
    return dok


def panel(tenant, rola="owner", nazwa="wl"):
    uzytkownik = CustomUser.objects.create_user(
        username=nazwa, email=f"{nazwa}@firma.pl", password="x", tenant=tenant, role=rola
    )
    klient = APIClient()
    klient.force_authenticate(user=uzytkownik)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return klient


def szukaj(tenant, monkeypatch, odleglosc_pytania=0.0):
    """Wyszukiwanie z podstawionym wektorem pytania — bez ruchu na zewnątrz."""
    from unittest.mock import MagicMock

    import rag.engine as silnik

    klient = MagicMock()
    klient.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=wektor(odleglosc_pytania))]
    )
    monkeypatch.setattr(silnik, "client", klient)
    return query_similar_chunks_pgvector(tenant.id, "pytanie", max_distance=99)


@pytest.mark.django_db
class TestWyszukiwania:
    def test_wylaczony_dokument_nie_trafia_do_wynikow(self, firma, monkeypatch):
        """Sedno. Fragment moze byc najblizszy i mimo to ma nie wychodzic."""
        kontakt = dokument(firma, "Kontakt", 0.1)
        dokument(firma, "Cennik", 0.5)

        przed = [c.document.name for c in szukaj(firma, monkeypatch)]
        kontakt.uzywaj_w_wyszukiwaniu = False
        kontakt.save()
        po = [c.document.name for c in szukaj(firma, monkeypatch)]

        assert przed == ["Kontakt", "Cennik"]
        assert po == ["Cennik"]

    def test_fragmenty_zostaja_w_bazie(self, firma, monkeypatch):
        """Wylaczenie ma byc natychmiast odwracalne. Kasowanie fragmentow
        oznaczaloby, ze wlaczenie z powrotem kosztuje ponowne liczenie
        wektorow — czyli pieniadze i czekanie."""
        kontakt = dokument(firma, "Kontakt", 0.1)

        kontakt.uzywaj_w_wyszukiwaniu = False
        kontakt.save()

        assert DocumentChunk.objects.filter(document=kontakt).count() == 1

    def test_wlaczenie_z_powrotem_dziala_od_razu(self, firma, monkeypatch):
        kontakt = dokument(firma, "Kontakt", 0.1)
        kontakt.uzywaj_w_wyszukiwaniu = False
        kontakt.save()

        kontakt.uzywaj_w_wyszukiwaniu = True
        kontakt.save()

        assert [c.document.name for c in szukaj(firma, monkeypatch)] == ["Kontakt"]

    def test_domyslnie_wszystko_jest_wlaczone(self, firma):
        """Klient nie ma nic robic, zeby bot dzialal — wylaczanie jest wyjatkiem."""
        assert dokument(firma, "Cokolwiek", 0.1).uzywaj_w_wyszukiwaniu is True

    def test_wylaczenie_u_jednej_firmy_nie_rusza_drugiej(self, firma, monkeypatch, db):
        obca = Tenant.objects.create(name="Obca", owner_email="o@b.pl")
        dokument(obca, "Kontakt", 0.1)
        moj = dokument(firma, "Kontakt", 0.1)

        moj.uzywaj_w_wyszukiwaniu = False
        moj.save()

        assert [c.document.name for c in szukaj(obca, monkeypatch)] == ["Kontakt"]


@pytest.mark.django_db
class TestPanelu:
    def test_lista_pokazuje_stan(self, firma):
        dokument(firma, "Kontakt", 0.1)

        odp = panel(firma).get("/api/documents/")

        dane = odp.json()
        pozycje = dane["results"] if isinstance(dane, dict) else dane
        assert pozycje[0]["uzywaj_w_wyszukiwaniu"] is True

    def test_wlasciciel_wylacza_dokument(self, firma):
        kontakt = dokument(firma, "Kontakt", 0.1)

        odp = panel(firma).patch(
            f"/api/documents/{kontakt.id}/wyszukiwanie/",
            {"uzywaj_w_wyszukiwaniu": False}, format="json",
        )

        assert odp.status_code == 200
        kontakt.refresh_from_db()
        assert kontakt.uzywaj_w_wyszukiwaniu is False

    def test_pracownik_tez_moze(self, firma):
        """Baza wiedzy to codzienna robota, nie decyzja wlascicielska."""
        kontakt = dokument(firma, "Kontakt", 0.1)

        odp = panel(firma, rola="employee", nazwa="prac").patch(
            f"/api/documents/{kontakt.id}/wyszukiwanie/",
            {"uzywaj_w_wyszukiwaniu": False}, format="json",
        )

        assert odp.status_code == 200

    def test_wartosc_z_formularza_jako_tekst(self, firma):
        """Panel wysyla czasem multipart, gdzie false to napis "false"."""
        kontakt = dokument(firma, "Kontakt", 0.1)

        panel(firma).patch(
            f"/api/documents/{kontakt.id}/wyszukiwanie/",
            {"uzywaj_w_wyszukiwaniu": "false"}, format="json",
        )

        kontakt.refresh_from_db()
        assert kontakt.uzywaj_w_wyszukiwaniu is False

    def test_brak_pola_to_blad_zadania(self, firma):
        kontakt = dokument(firma, "Kontakt", 0.1)

        odp = panel(firma).patch(f"/api/documents/{kontakt.id}/wyszukiwanie/", {}, format="json")

        assert odp.status_code == 400

    def test_nie_da_sie_ruszyc_cudzego_dokumentu(self, firma, db):
        obca = Tenant.objects.create(name="Obca", owner_email="o@b.pl")
        cudzy = dokument(obca, "Kontakt", 0.1)

        odp = panel(firma).patch(
            f"/api/documents/{cudzy.id}/wyszukiwanie/",
            {"uzywaj_w_wyszukiwaniu": False}, format="json",
        )

        assert odp.status_code == 404
        cudzy.refresh_from_db()
        assert cudzy.uzywaj_w_wyszukiwaniu is True

    def test_tresci_nie_da_sie_podmienic_ta_droga(self, firma):
        """Otwarcie calego zasobu do zapisu pozwoliloby zmienic tresc bez
        przeliczenia fragmentow — bot odpowiadalby wtedy z wektorow
        policzonych dla czegos innego, niz widac w panelu."""
        kontakt = dokument(firma, "Kontakt", 0.1)

        panel(firma).patch(
            f"/api/documents/{kontakt.id}/wyszukiwanie/",
            {"uzywaj_w_wyszukiwaniu": False, "content": "PODMIENIONE", "name": "Inna"},
            format="json",
        )

        kontakt.refresh_from_db()
        assert kontakt.content == "tresc"
        assert kontakt.name == "Kontakt"


@pytest.mark.django_db
class TestTrwalosciPrzyOdswiezaniu:
    def test_wylaczenie_przezywa_odswiezenie_strony(self, firma):
        """
        To jedyny sposob, zeby trwale wylaczyc podstrone pobrana ze strony WWW:
        skasowany dokument wroci przy najblizszym odswiezeniu, wylaczony
        zostaje wylaczony.
        """
        from unittest.mock import patch

        from documents.website_import import import_website_as_document

        adres = "https://agencjasm-art.pl/kontakt"
        with patch("documents.website_import.fetch_text_from_url",
                   return_value=TrescStrony("KONTAKT\n\nPorozmawiajmy.", 400)):
            dok = import_website_as_document(firma, adres, name=adres)
        dok.uzywaj_w_wyszukiwaniu = False
        dok.save()

        with patch("documents.website_import.fetch_text_from_url",
                   return_value=TrescStrony("KONTAKT\n\nNowa tresc sekcji.", 400)):
            import_website_as_document(firma, adres, name=adres)

        dok.refresh_from_db()
        assert dok.uzywaj_w_wyszukiwaniu is False
        assert "Nowa tresc" in dok.content


@pytest.mark.django_db
class TestNarzedziaPomiarowego:
    """
    Komenda zmierz_prog_rag miala wlasna kopie zapytania o fragmenty, bez
    filtra wylaczonych dokumentow. Skutek byl gorszy niz zwykly blad: bot
    pomijal odznaczona sekcje poprawnie, a przyrzad pokazywal, ze nie pomija.
    Wygladalo to na niedzialajaca funkcje i prowadzilo do szukania usterki
    tam, gdzie jej nie bylo.

    Teraz obie sciezki wolaja fragmenty_do_przeszukania().
    """

    def test_pomiar_pomija_wylaczone_dokumenty(self, firma, monkeypatch):
        from io import StringIO
        from unittest.mock import MagicMock

        from django.core.management import call_command

        from chat.models import Conversation, PromptLog

        kontakt = dokument(firma, "Kontakt", 0.1)
        dokument(firma, "Cennik", 0.5)

        rozmowa = Conversation.objects.create(
            tenant=firma, user_identifier="gosc", source="widget"
        )
        PromptLog.objects.create(
            tenant=firma, conversation=rozmowa, model="m",
            prompt="Czy naprawiacie pralki?", source="document",
        )

        klient = MagicMock()
        klient.embeddings.create.return_value = MagicMock(
            data=[MagicMock(index=0, embedding=wektor(0.0))]
        )
        monkeypatch.setattr(
            "documents.management.commands.zmierz_prog_rag.get_client",
            lambda tenant=None: klient,
        )

        def zmierz():
            wyjscie = StringIO()
            call_command("zmierz_prog_rag", firma=firma.id, stdout=wyjscie)
            return wyjscie.getvalue()

        assert "FRAGMENT Kontakt" in zmierz()

        kontakt.uzywaj_w_wyszukiwaniu = False
        kontakt.save()

        po = zmierz()
        assert "FRAGMENT Kontakt" not in po
        assert "FRAGMENT Cennik" in po
