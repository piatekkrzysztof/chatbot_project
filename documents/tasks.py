import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.plans import recrawl_days_for
from documents.file_limits import MAX_DOCUMENT_BYTES, InvalidUpload, UploadTooLarge
from documents.models import Document, WebsiteSource
from documents.safe_http import crawl_fetch_budget, same_site
from documents.sitemaps import sitemap_search
from documents.utils.embedding_generator import (
    generate_embeddings_for_document as _generate_embeddings,
)
from documents.utils.queue import enqueue
from documents.utils.text_extraction import UnsupportedFileType, extract_text
from documents.validators import sprawdz_limit_bazy_wiedzy
from documents.website_import import discover_links_recursively, import_website_as_document

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
        # Reject oversized legacy/admin files before remote storage downloads them.
        if doc.file.size > MAX_DOCUMENT_BYTES:
            raise UploadTooLarge("Dokument przekracza limit 10 MiB.")
        # Otwieramy przez magazyn, nie przez ścieżkę na dysku: .path istnieje
        # tylko dla FileSystemStorage i na S3/R2 rzuca NotImplementedError.
        with doc.file.open("rb") as handle:
            content = extract_text(handle, filename=doc.file.name)
        if not content:
            raise InvalidUpload("Brak tekstu w dokumencie. Dla skanu najpierw wykonaj OCR.")
        sprawdz_limit_bazy_wiedzy(doc.tenant, content, zastepowany_tekst=doc.content)
        doc.content = content
        doc.processed = True
        doc.processing_error = ""
        doc.save()
    except (InvalidUpload, UnsupportedFileType, ValidationError) as error:
        message = (
            "Dokument przekracza limit bazy wiedzy w Twoim planie. Zmniejsz plik."
            if isinstance(error, ValidationError)
            else "Obsługiwane dokumenty: PDF, DOCX, TXT i MD."
            if isinstance(error, UnsupportedFileType)
            else str(error)
        )
        Document.objects.filter(pk=document_id).update(processing_error=message[:300])
        logger.warning("Odrzucono przetwarzanie dokumentu %s", document_id)
    except Exception:
        Document.objects.filter(pk=document_id).update(
            processing_error="Nie udało się przetworzyć pliku. Spróbuj wgrać go ponownie."
        )
        logger.error("Błąd przetwarzania dokumentu %s", document_id)


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
    # One budget covers robots, nested sitemaps, redirects, discovery and imports.
    with crawl_fetch_budget():
        _crawl_and_import_website_source(source_id)


def _crawl_and_import_website_source(source_id):
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
            if not same_site(suburl, url):
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

        if pobranych == 0 and not nieudanych:
            raise ValueError("Nie znaleziono dozwolonych podstron w domenie źródła.")

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
