import logging

from celery import shared_task
from documents.utils.text_extraction import extract_text, UnsupportedFileType
from documents.models import Document, DocumentChunk, WebsiteSource
from documents.website_import import discover_links_recursively
from documents.utils.embedding_generator import generate_embeddings_for_document as _generate_embeddings
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
        print(f"⚠️ Dokument {document.id} nie zawiera treści.")
        return
    _generate_embeddings(document)


MAX_PAGES_PER_CRAWL = 20


@shared_task
def crawl_and_import_website_source(source_id):
    try:
        source = WebsiteSource.objects.select_related("tenant").get(id=source_id)
        url = source.url
        tenant = source.tenant

        # pobierz podstrony z sitemap (ograniczone do rozsądnej liczby, sitemapa bywa ogromna)

        urls = (sitemap_search(source.url) or [])[:MAX_PAGES_PER_CRAWL]
        if not urls:
            urls = discover_links_recursively(source.url, max_depth=2, max_pages=MAX_PAGES_PER_CRAWL)

        if not urls:
            urls = [url]  # fallback – tylko główna strona

        for suburl in urls:
            if not suburl.startswith(url):  # zabezpieczenie przed ucieczką poza domenę
                continue

            # sprawdź, czy dokument już istnieje
            if Document.objects.filter(tenant=tenant, source="website", name=suburl).exists():
                continue

            try:
                import_website_as_document(tenant=tenant, url=suburl, name=suburl)
            except Exception as e:
                print(f"⚠️ Błąd podczas importu {suburl}: {e}")

        print(f"✅ Zakończono crawling {url} (source_id={source_id})")

        WebsiteSource.objects.filter(pk=source_id).update(last_crawled_at=timezone.now())

    except WebsiteSource.DoesNotExist:
        print(f"❌ Nie znaleziono WebsiteSource z ID {source_id}")


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
