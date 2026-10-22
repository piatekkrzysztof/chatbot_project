"""
Fragmenty z wyszukiwania przychodzą razem z dokumentem (audyt 2026-10, P20).

Prompt i lista źródeł pod odpowiedzią czytają nazwę i adres dokumentu każdego
fragmentu. Wyszukiwanie nie dociągało dokumentu, więc każdy fragment to było
osobne zapytanie do bazy - pięć dodatkowych przy każdej wiadomości czatu.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import Tenant
from api.utils.chat_engine import zrodla_do_pokazania
from api.utils.prompt_systemowy import build_system_prompt
from documents.models import Document, DocumentChunk
from rag.engine import dolacz_trafienia_slowne, szukaj_po_wektorze

WEKTOR = [0.0] * 512


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Fragmenty")
    for numer in range(5):
        dokument = Document.objects.create(
            tenant=tenant,
            name=f"cennik {numer}",
            content="treść",
            source_url=f"https://example.com/{numer}",
        )
        DocumentChunk.objects.create(
            document=dokument, content=f"Tort weselny {numer} kosztuje 300 zł", embedding=WEKTOR
        )
    return tenant


def zapytania_przy_uzyciu(tenant, fragmenty):
    with CaptureQueriesContext(connection) as zapytania:
        build_system_prompt(tenant, fragmenty, [], "Ile kosztuje tort weselny?")
        zrodla_do_pokazania(fragmenty, "document")
    return len(zapytania.captured_queries)


@pytest.mark.django_db
def test_fragmenty_z_wyszukiwania_wektorowego_nie_dopytuja_o_dokument(firma):
    fragmenty = szukaj_po_wektorze(firma.id, WEKTOR, top_k=5, max_distance=1.0)

    assert len(fragmenty) == 5
    assert zapytania_przy_uzyciu(firma, fragmenty) == 0


@pytest.mark.django_db
def test_fragmenty_z_trafien_slownych_nie_dopytuja_o_dokument(firma):
    fragmenty = dolacz_trafienia_slowne(firma.id, "Ile kosztuje tort weselny?", WEKTOR, [], 5)

    assert fragmenty
    assert zapytania_przy_uzyciu(firma, fragmenty) == 0


@pytest.mark.django_db
def test_zrodla_nadal_maja_nazwe_i_adres(firma):
    fragmenty = szukaj_po_wektorze(firma.id, WEKTOR, top_k=5, max_distance=1.0)

    zrodla = zrodla_do_pokazania(fragmenty, "document")

    assert {"name": "cennik 0", "url": "https://example.com/0"} in zrodla
    assert len(zrodla) == 5
