"""
Pomiar progu odległości dla wyszukiwania fragmentów.

Komenda liczy, gdzie powinien przebiegać RAG_MAX_DISTANCE: między pytaniami,
na które baza wiedzy odpowiada, a tymi, na które nie.

Pierwsza wersja brała wszystkie pytania z historii do jednego worka i liczyła
granicę między nimi a pytaniami kontrolnymi. Na prawdziwych danych dało to
wniosek odwrotny do poprawnego — sugerowała PODNIESIENIE progu, bo w historii
siedziały też pytania bez pokrycia i to one wyznaczały górną krawędź grupy.
Podniesienie progu wpuściłoby do promptu dokładnie te fragmenty, które nie
odpowiadają na pytanie.

Ten test pilnuje, że grupy są rozdzielane po zapisanym źródle odpowiedzi.
"""
from io import StringIO
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Tenant
from chat.models import Conversation, PromptLog
from documents.models import Document, DocumentChunk

WYMIAR = 1536


def wektor(pierwsza_wspolrzedna):
    """Wektor na osi — odległość L2 między dwoma takimi to różnica współrzędnych."""
    v = [0.0] * WYMIAR
    v[0] = pierwsza_wspolrzedna
    return v


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Pomiar", owner_email="a@b.pl")
    dokument = Document.objects.create(tenant=tenant, name="Oferta", content="tresc")
    DocumentChunk.objects.create(document=dokument, content="FRAGMENT", embedding=wektor(0.0))
    return tenant


def zapytaj(tenant, tresc, zrodlo):
    rozmowa, _ = Conversation.objects.get_or_create(
        tenant=tenant, user_identifier="gosc", defaults={"source": "widget"}
    )
    PromptLog.objects.create(
        tenant=tenant, conversation=rozmowa, model="m", prompt=tresc, source=zrodlo
    )


def udawane_wektory(monkeypatch, odleglosci):
    """
    Podmienia model embeddingów tak, że każde pytanie leży w zadanej odległości
    od jedynego fragmentu (który stoi w zerze).
    """
    klient = MagicMock()

    def create(model, input):
        tresc = input if isinstance(input, str) else input[0]
        return MagicMock(data=[MagicMock(index=0, embedding=wektor(odleglosci.get(tresc, 9.0)))])

    klient.embeddings.create.side_effect = create
    monkeypatch.setattr(
        "documents.management.commands.zmierz_prog_rag.get_client",
        lambda tenant=None: klient,
    )
    return klient


def uruchom(tenant):
    wyjscie = StringIO()
    call_command("zmierz_prog_rag", firma=tenant.id, stdout=wyjscie)
    return wyjscie.getvalue()


@pytest.mark.django_db
class TestRozdzielaniaGrup:
    def test_prog_lezy_miedzy_pokrytymi_a_niepokrytymi(self, firma, monkeypatch):
        """
        Sedno. Pytanie bez pokrycia lezy blizej (1.0) niz pytania kontrolne
        (9.0), wiec to ONO wyznacza gorna granice. Liczenie wspolnej grupy
        z historii dawaloby prog okolo 5.0 — czyli wpuszczaloby wszystko.
        """
        udawane_wektory(monkeypatch, {
            "Ile kosztuje sala?": 0.4,
            "Jakie sa godziny otwarcia?": 1.0,
        })
        zapytaj(firma, "Ile kosztuje sala?", "document")
        zapytaj(firma, "Jakie sa godziny otwarcia?", "gpt")

        wynik = uruchom(firma)

        assert "Próg rozdzielający grupy: 0.70" in wynik, wynik

    def test_pytania_bez_pokrycia_sa_w_osobnej_sekcji(self, firma, monkeypatch):
        udawane_wektory(monkeypatch, {"A": 0.4, "B": 1.0})
        zapytaj(firma, "A", "document")
        zapytaj(firma, "B", "gpt")

        wynik = uruchom(firma)

        assert "BOT ODPOWIEDZIAŁ Z BAZY" in wynik
        assert "BOT NIE ZNALAZŁ ODPOWIEDZI" in wynik

    def test_odpowiedzi_z_faq_licza_sie_jako_pokryte(self, firma, monkeypatch):
        """Zrodlo 'faq' tez znaczy, ze baza wiedzy pokryla pytanie."""
        udawane_wektory(monkeypatch, {"A": 0.4, "B": 1.0})
        zapytaj(firma, "A", "faq")
        zapytaj(firma, "B", "gpt")

        assert "Próg rozdzielający grupy: 0.70" in uruchom(firma)

    def test_nakladajace_sie_grupy_sa_nazwane_wprost(self, firma, monkeypatch):
        """Gdy pytanie bez pokrycia lezy BLIZEJ niz pokryte, zaden prog nie
        pomoze — i komenda ma to powiedziec, zamiast podawac liczbe."""
        udawane_wektory(monkeypatch, {"A": 1.0, "B": 0.4})
        zapytaj(firma, "A", "document")
        zapytaj(firma, "B", "gpt")

        wynik = uruchom(firma)

        assert "nakładają" in wynik
        assert "Próg rozdzielający grupy" not in wynik

    def test_rozmowy_testowe_nie_wchodza_do_pomiaru(self, firma, monkeypatch):
        """Wlasciciel testuje bota trudnymi pytaniami — przesunelyby granice."""
        udawane_wektory(monkeypatch, {"A": 0.4, "T": 0.9})
        zapytaj(firma, "A", "document")

        testowa = Conversation.objects.create(
            tenant=firma, user_identifier="panel:1", source="test"
        )
        PromptLog.objects.create(
            tenant=firma, conversation=testowa, model="m", prompt="T", source="gpt"
        )

        wynik = uruchom(firma)

        assert "BOT NIE ZNALAZŁ ODPOWIEDZI" not in wynik


@pytest.mark.django_db
class TestZabezpieczen:
    def test_firma_bez_fragmentow_konczy_komunikatem(self, db, monkeypatch):
        pusta = Tenant.objects.create(name="Pusta", owner_email="a@b.pl")

        with pytest.raises(CommandError, match="nie ma żadnych fragmentów"):
            uruchom(pusta)

    def test_nieistniejaca_firma_konczy_komunikatem(self, db):
        with pytest.raises(CommandError, match="Nie ma firmy"):
            call_command("zmierz_prog_rag", firma=999999, stdout=StringIO())

    def test_komenda_niczego_nie_zmienia(self, firma, monkeypatch):
        """To narzedzie diagnostyczne — ma tylko liczyc i wypisywac."""
        udawane_wektory(monkeypatch, {"A": 0.4})
        zapytaj(firma, "A", "document")
        przed = list(DocumentChunk.objects.values_list("id", "content"))

        uruchom(firma)

        assert list(DocumentChunk.objects.values_list("id", "content")) == przed
