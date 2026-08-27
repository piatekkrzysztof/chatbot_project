import logging

from celery import shared_task
from documents.utils.text_extraction import extract_text, UnsupportedFileType
from documents.models import Document, DocumentChunk, WebsiteSource
from documents.website_import import discover_links_recursively
from documents.utils.embedding_generator import (
    generate_embeddings_for_document as _generate_embeddings,
)
from documents.utils.queue import enqueue
from datetime import timedelta

from django.utils import timezone

from accounts.plans import recrawl_days_for
from documents.website_import import import_website_as_document
from trafilatura.sitemaps import sitemap_search

logger = logging.getLogger(__name__)


@shared_task
def embed_document_task(document_id: int):
    doc = Document.objects.get(id=document_id)
    _generate_embeddings(doc)


@shared_task
def extract_text_from_document(document_id):
    try:
        doc = Document.objects.get(id=document_id)
        if not doc.file:
            return

        # Otwieramy przez magazyn, nie przez ścieżkę na dysku: .path istnieje
        # tylko dla FileSystemStorage i na S3/R2 rzuca NotImplementedError.
        with doc.file.open("rb") as handle:
            doc.content = extract_text(handle, filename=doc.file.name)
        doc.processed = True
        doc.save()
    except UnsupportedFileType as e:
        logger.warning("Dokument %s: %s", document_id, e)
    except Exception as e:
        logger.exception("Błąd przetwarzania dokumentu %s: %s", document_id, e)


@shared_task
def generate_embeddings_for_document(document_id):
    document = Document.objects.select_related("tenant").get(id=document_id)
    if not document.content:
        logger.warning("Dokument %s nie zawiera treści — pomijam embeddingi.", document.id)
        return
    _generate_embeddings(document)


MAX_PAGES_PER_CRAWL = 20


@shared_task
def crawl_and_import_website_source(source_id):
    # Znacznik próby stawiamy PRZED pracą, nie po. Dzięki temu zadanie, które
    # wywali się w połowie, zostawia ślad — inaczej nieudane pobranie wygląda
    # dokładnie tak samo jak takie, którego nigdy nie zlecono.
    WebsiteSource.objects.filter(pk=source_id).update(last_attempt_at=timezone.now())
    try:
        source = WebsiteSource.objects.select_related("tenant").get(id=source_id)
        url = source.url
        tenant = source.tenant

        # pobierz podstrony z sitemap (ograniczone do rozsądnej liczby, sitemapa bywa ogromna)

        urls = (sitemap_search(source.url) or [])[:MAX_PAGES_PER_CRAWL]
        if not urls:
            urls = discover_links_recursively(
                source.url, max_depth=2, max_pages=MAX_PAGES_PER_CRAWL
            )

        if not urls:
            urls = [url]  # fallback – tylko główna strona

        pobranych, nieudanych = 0, []

        for suburl in urls:
            if not suburl.startswith(url):  # zabezpieczenie przed ucieczką poza domenę
                continue

            # Znane podstrony ODŚWIEŻAMY, nie pomijamy. Wcześniej stało tu
            # `continue` dla adresów już obecnych w bazie, przez co cykliczne
            # pobieranie z cennika (Grow co 7 dni, Pro codziennie) nie zmieniało
            # niczego: bot odpowiadał z wersji pobranej za pierwszym razem, choć
            # klient dawno zmienił na stronie ceny i godziny. Sam import wykrywa
            # brak zmian i wtedy nie rusza fragmentów.
            try:
                import_website_as_document(tenant=tenant, url=suburl, name=suburl)
                pobranych += 1
            except Exception as e:
                # Jedna niedostępna podstrona nie może przerwać pobierania
                # pozostałych — inaczej awaria na trzeciej z dwudziestu
                # zostawia bazę wiedzy w połowie odświeżoną.
                nieudanych.append(f"{suburl}: {e}")
                logger.warning("Błąd podczas importu %s: %s", suburl, e)

        logger.info(
            "Zakończono pobieranie %s (source_id=%s): %d z %d podstron",
            url,
            source_id,
            pobranych,
            pobranych + len(nieudanych),
        )

        if pobranych == 0 and nieudanych:
            # Zero pobranych podstron to awaria, nie sukces — nawet jeśli każda
            # z osobna „tylko" się nie udała. Wcześniej zadanie zapisywało tu
            # last_crawled_at i puste last_error, więc panel pokazywał
            # „pobieranie stron: działa", a klient miał pustą bazę wiedzy.
            # Wyszło to przy próbie generalnej onboardingu: dwadzieścia
            # podstron, dwadzieścia błędów, zielony status.
            WebsiteSource.objects.filter(pk=source_id).update(
                last_error=f"Żadna z {len(nieudanych)} podstron nie została pobrana. "
                f"Pierwszy błąd — {nieudanych[0][:200]}"
            )
            return

        WebsiteSource.objects.filter(pk=source_id).update(
            last_crawled_at=timezone.now(),
            # Częściowe niepowodzenie zostawia ślad, ale nie blokuje: reszta
            # wiedzy jest już w bazie i bot z niej korzysta.
            last_error=(
                f"Nie udało się pobrać {len(nieudanych)} z {pobranych + len(nieudanych)} "
                f"podstron. Pierwsza — {nieudanych[0][:200]}"
            )
            if nieudanych
            else "",
        )

    except WebsiteSource.DoesNotExist:
        logger.error("Nie znaleziono źródła WWW o id %s", source_id)
    except Exception as blad:
        # Wcześniej łapaliśmy wyłącznie DoesNotExist, więc każdy inny błąd —
        # nieosiągalna strona, timeout, certyfikat, błąd parsowania — wywalał
        # zadanie i nie zostawiał śladu nigdzie poza logiem workera. Klient
        # widział bota bez wiedzy i nie miał jak dojść dlaczego.
        logger.exception("Nie udało się pobrać źródła WWW %s", source_id)
        WebsiteSource.objects.filter(pk=source_id).update(
            last_error=f"{type(blad).__name__}: {str(blad)[:500]}"
        )


@shared_task
def crawl_all_active_sources():
    """
    Cykliczne odświeżanie treści ze stron klientów.

    Zadanie chodzi często, ale to nie ono decyduje o częstotliwości — decyduje
    plan każdej firmy. Wcześniej każdy przebieg pobierał wszystkie źródła
    niezależnie od planu, choć cennik obiecuje odświeżanie ręczne, tygodniowe
    albo dzienne. Każdy przebieg to ruch na stronie klienta i przeliczenie
    embeddingów, więc różnica jest realna, nie tylko cennikowa.
    """
    teraz = timezone.now()
    zlecone = 0

    for source in WebsiteSource.objects.filter(is_active=True).select_related("tenant"):
        subskrypcja = getattr(source.tenant, "subscription", None)
        co_ile_dni = recrawl_days_for(getattr(subskrypcja, "plan_type", None))

        # None: plan bez automatycznego odświeżania — czeka na ręczne zlecenie
        if co_ile_dni is None:
            continue

        if source.last_crawled_at and source.last_crawled_at > teraz - timedelta(days=co_ile_dni):
            continue

        enqueue(crawl_and_import_website_source, source.id)
        zlecone += 1

    return zlecone
