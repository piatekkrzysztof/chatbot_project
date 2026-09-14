"""
F16, część 2: listy wiedzy stronami, limit publicznego FAQ, eksport CSV jako strumień.

* Import strony zakłada dokument na każdą podstronę (do 20 na źródło), a źródeł
  nie ogranicza plan - lista dokumentów szła w całości przy każdym wejściu.
* FAQ nie ma górnej granicy liczby wpisów.
* Publiczne FAQ widgetu (bez logowania, sam klucz z kodu widgetu) oddawało całe
  FAQ firmy jednym żądaniem.
* Eksport CSV budował cały plik w pamięci procesu, zanim wysłał pierwszy bajt.
"""

import csv
import io

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from api.tests.test_wydajnosc_list import firma_z_wlascicielem, klient
from chat.models import FAQ, Conversation, PromptLog
from documents.models import Document

#: Limit publicznego FAQ widgetu (api/views/widget.py). Zapisany tu wprost, żeby
#: test dało się uruchomić także na kodzie sprzed zmiany.
MAKS_FAQ_WIDGETU = 100


@pytest.fixture
def firma(db):
    return firma_z_wlascicielem("wiedza")


@pytest.mark.django_db
class TestListWiedzy:
    def test_dokumenty_stronami_od_najnowszych(self, firma):
        tenant, wlasciciel = firma
        for i in range(55):
            Document.objects.create(tenant=tenant, name=f"dok {i}", processed=True)

        dane = klient(tenant, wlasciciel).get("/api/documents/").json()
        druga = klient(tenant, wlasciciel).get("/api/documents/?page=2").json()

        assert dane["count"] == 55
        assert len(dane["results"]) == 50
        assert dane["results"][0]["name"] == "dok 54"
        assert len(druga["results"]) == 5

    def test_faq_stronami_od_najnowszych(self, firma):
        tenant, wlasciciel = firma
        for i in range(55):
            FAQ.objects.create(tenant=tenant, question=f"pytanie {i}", answer="x")

        dane = klient(tenant, wlasciciel).get("/api/faq/").json()

        assert dane["count"] == 55
        assert len(dane["results"]) == 50
        # Właśnie dodany wpis ma być na pierwszej stronie
        assert dane["results"][0]["question"] == "pytanie 54"

    def test_publiczne_faq_ma_gorny_limit(self, firma):
        tenant, _ = firma
        FAQ.objects.bulk_create(
            FAQ(tenant=tenant, question=f"pytanie {i}", answer="x")
            for i in range(MAKS_FAQ_WIDGETU + 5)
        )
        from rest_framework.test import APIClient

        odpowiedz = APIClient().get("/api/widget/faq/", HTTP_X_API_KEY=str(tenant.api_key))

        assert odpowiedz.status_code == 200
        assert len(odpowiedz.json()) == MAKS_FAQ_WIDGETU


def logi(tenant, ile):
    rozmowa = Conversation.objects.create(tenant=tenant, user_identifier="gosc")
    PromptLog.objects.bulk_create(
        PromptLog(
            tenant=tenant,
            conversation=rozmowa,
            model="m",
            prompt=f"=pytanie {i}" if i == 0 else f"pytanie {i}",
            source="faq",
            response="odpowiedź",
        )
        for i in range(ile)
    )


@pytest.mark.django_db
class TestEksportu:
    def test_eksport_jest_strumieniem(self, firma):
        tenant, wlasciciel = firma
        logi(tenant, 3)

        odpowiedz = klient(tenant, wlasciciel).get("/api/chat/export/")

        assert odpowiedz.status_code == 200
        assert odpowiedz.streaming is True
        assert odpowiedz["Content-Type"] == "text/csv"
        assert "attachment" in odpowiedz["Content-Disposition"]

    def test_tresc_strumienia_bez_zmian(self, firma):
        """Straż: BOM, nagłówek, neutralizacja formuł i wszystkie wiersze jak dotąd."""
        tenant, wlasciciel = firma
        logi(tenant, 1205)

        odpowiedz = klient(tenant, wlasciciel).get("/api/chat/export/")
        pierwszy = next(iter(odpowiedz.streaming_content))
        reszta = b"".join(odpowiedz.streaming_content)
        wiersze = list(csv.reader(io.StringIO((pierwszy + reszta).decode("utf-8").lstrip("﻿"))))

        assert pierwszy.startswith(b"\xef\xbb\xbf")
        assert wiersze[0][:3] == ["conversation_id", "prompt", "response"]
        assert len(wiersze) == 1206
        assert "'=pytanie 0" in {w[1] for w in wiersze[1:]}

    def test_eksport_czyta_historie_porcjami(self, firma):
        # Liczba zapytań nie rośnie z liczbą wierszy (iterator z porcjami).
        tenant, wlasciciel = firma
        inna, wlasciciel_innej = firma_z_wlascicielem("duza-historia")
        logi(tenant, 3)
        logi(inna, 300)

        def zapytania_eksportu(t, w):
            odpowiedz = klient(t, w).get("/api/chat/export/")
            with CaptureQueriesContext(connection) as zapytania:
                b"".join(odpowiedz.streaming_content)
            return len(zapytania)

        assert zapytania_eksportu(inna, wlasciciel_innej) == zapytania_eksportu(tenant, wlasciciel)
