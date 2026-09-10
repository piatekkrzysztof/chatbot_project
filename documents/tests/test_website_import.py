from unittest.mock import Mock, patch

import pytest

from accounts.models import Tenant
from documents.models import Document
from documents.safe_http import Page
from documents.website_import import (
    discover_links_recursively,
    fetch_text_from_url,
    import_website_as_document,
)

HTML_MAIN = """
<html>
    <body>
        <h1>Witamy na stronie</h1>
        <a href="/faq">FAQ</a>
    </body>
</html>
"""

HTML_FAQ = """
<html>
    <body>
        <h2>Najczęstsze pytania</h2>
        <p>Jak działa system?</p>
    </body>
</html>
"""

TRAFILATURA_EXTRACT_MOCK = {
    "http://example.com/": "Witamy na stronie\nFAQ\n" + "To jest główna strona. " * 10,
    "http://example.com/faq": "Najczęstsze pytania\n" + "Jak działa system? " * 10,
}


@pytest.mark.django_db
@patch("documents.utils.tresc_strony.trafilatura.extract")
@patch("documents.website_import.fetch_page")
def test_import_website_deep_crawl(mock_fetch_page, mock_extract, tenant: Tenant):
    def mocked_fetch_page(url):
        html = HTML_MAIN if url.endswith("/") else HTML_FAQ
        return Page(url, html.encode())

    mock_fetch_page.side_effect = mocked_fetch_page
    mock_extract.side_effect = lambda html, **kwargs: TRAFILATURA_EXTRACT_MOCK.get(
        "http://example.com/" if b"Witamy" in html else "http://example.com/faq"
    )

    discovered_urls = discover_links_recursively("http://example.com/", max_depth=1)
    assert "http://example.com/" in discovered_urls
    assert "http://example.com/faq" in discovered_urls

    for url in discovered_urls:
        doc = import_website_as_document(tenant=tenant, url=url, name=url)
        assert isinstance(doc, Document)
        assert doc.content.strip() != ""
        assert doc.name == url
        assert doc.source == "website"
