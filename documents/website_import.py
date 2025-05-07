import requests
import trafilatura
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

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


def discover_links_recursively(base_url: str, max_depth: int = 2) -> set[str]:
    """
    Heurystyczny crawler: podąża za linkami wewnętrznymi w obrębie jednej domeny.
    """
    visited = set()
    to_visit = [(base_url, 0)]
    base_domain = urlparse(base_url).netloc

    while to_visit:
        current_url, depth = to_visit.pop()
        if current_url in visited or depth > max_depth:
            continue

        visited.add(current_url)

        try:
            resp = requests.get(current_url, timeout=5)
            resp.raise_for_status()
        except Exception:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for link_tag in soup.find_all("a", href=True):
            href = link_tag["href"]
            absolute_url = urljoin(current_url, href)
            parsed = urlparse(absolute_url)

            if parsed.netloc == base_domain and parsed.scheme.startswith("http"):
                to_visit.append((absolute_url, depth + 1))

    return visited
