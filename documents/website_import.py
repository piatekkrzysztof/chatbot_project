import trafilatura
from documents.models import Document
from documents.tasks import generate_embeddings_for_document


def fetch_text_from_url(url: str) -> str:
    """
    Pobiera czysty tekst ze strony internetowej.
    """
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Nie udało się pobrać zawartości URL: {url}")

    extracted = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        include_formatting=False
    )

    if not extracted or len(extracted.strip()) < 100:
        raise ValueError(f"Zbyt mało treści do wykorzystania z: {url}")

    return extracted.strip()


def import_website_as_document(tenant, url: str, name: str = "Strona WWW klienta") -> Document:
    """
    Pobiera stronę WWW, zapisuje jako Document, generuje embeddingi.
    """
    text = fetch_text_from_url(url)

    document = Document.objects.create(
        tenant=tenant,
        name=name,
        content=text,
        source="website"
    )

    generate_embeddings_for_document.delay(document.id)
    return document
