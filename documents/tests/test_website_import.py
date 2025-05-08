import pytest
from unittest.mock import patch, Mock
from documents.website_import import discover_links_recursively, fetch_text_from_url, import_website_as_document
from accounts.models import Tenant
from documents.models import Document

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
    "http://test.local/": "Witamy na stronie\nFAQ\n" + "To jest główna strona. " * 10,
    "http://test.local/faq": "Najczęstsze pytania\n" + "Jak działa system? " * 10,
}

@pytest.mark.django_db
@patch("documents.website_import.requests.get")
@patch("documents.website_import.trafilatura.extract")
@patch("documents.website_import.trafilatura.fetch_url")
def test_import_website_deep_crawl(mock_fetch_url, mock_extract, mock_get, tenant: Tenant):
    # przygotuj mocki response
    def mocked_requests_get(url, timeout=5):
        html = HTML_MAIN if url.endswith("/") else HTML_FAQ
        response = Mock()
        response.status_code = 200
        response.text = html
        response.raise_for_status = Mock()
        return response

    mock_get.side_effect = mocked_requests_get

    mock_fetch_url.side_effect = lambda url: HTML_MAIN if url.endswith("/") else HTML_FAQ
    mock_extract.side_effect = lambda html, **kwargs: TRAFILATURA_EXTRACT_MOCK.get(
        "http://test.local/" if "Witamy" in html else "http://test.local/faq"
    )

    discovered_urls = discover_links_recursively("http://test.local/", max_depth=1)
    assert "http://test.local/" in discovered_urls
    assert "http://test.local/faq" in discovered_urls

    for url in discovered_urls:
        doc = import_website_as_document(tenant=tenant, url=url, name=url)
        assert isinstance(doc, Document)
        assert doc.content.strip() != ""
        assert doc.name == url
        assert doc.source == "website"
