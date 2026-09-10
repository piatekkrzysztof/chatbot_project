import gzip
from unittest.mock import Mock

import pytest

from documents import sitemaps, website_import
from documents.safe_http import FetchError, FetchLimitExceeded, Page

ROOT = "https://example.com/"


def xml(kind, urls):
    entry = "sitemap" if kind == "sitemapindex" else "url"
    content = "".join(f"<{entry}><loc>{url}</loc></{entry}>" for url in urls)
    return (
        f'<{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{content}</{kind}>'.encode()
    )


def install(monkeypatch, responses):
    def fetch(url):
        if url not in responses:
            raise FetchError("HTTP 404")
        body = responses[url]
        return Page(url, body if isinstance(body, bytes) else body.encode())

    mock = Mock(side_effect=fetch)
    monkeypatch.setattr(sitemaps, "fetch_page", mock)
    return mock


def test_robots_nested_and_compressed_sitemaps_use_one_downloader(monkeypatch):
    fetch = install(
        monkeypatch,
        {
            ROOT + "robots.txt": "Sitemap: https://example.com/maps/index.xml\n"
            "Sitemap: http://127.0.0.1/private.xml\nSitemap: https://example.com.evil.org/map.xml",
            ROOT + "maps/index.xml": xml("sitemapindex", [ROOT + "maps/leaf.xml.gz"]),
            ROOT + "maps/leaf.xml.gz": gzip.compress(
                xml(
                    "urlset",
                    [
                        ROOT + "faq#one",
                        ROOT + "faq#two",
                        ROOT + "contact",
                        "http://127.0.0.1/",
                        "https://example.com.evil.org/",
                        "https://example.com@evil.org/",
                    ],
                )
            ),
        },
    )
    assert sitemaps.sitemap_search(ROOT) == [ROOT + "faq", ROOT + "contact"]
    assert [call.args[0] for call in fetch.call_args_list] == [
        ROOT + "robots.txt",
        ROOT + "sitemap.xml",
        ROOT + "maps/index.xml",
        ROOT + "maps/leaf.xml.gz",
    ]


def test_sitemap_file_count_and_page_count_are_bounded(monkeypatch):
    files = [ROOT + f"map-{i}.xml" for i in range(100)]
    pages = [ROOT + f"page-{i}" for i in range(100)]
    responses = {ROOT + "sitemap.xml": xml("sitemapindex", [ROOT + "sitemap.xml", *files])}
    responses.update({url: xml("urlset", pages) for url in files})
    fetch = install(monkeypatch, responses)
    assert sitemaps.sitemap_search(ROOT) == pages[:20]
    assert fetch.call_count <= 6  # robots + at most five sitemap files


def test_empty_recursive_sitemaps_do_not_exceed_file_budget(monkeypatch):
    urls = [ROOT + f"map-{i}.xml" for i in range(100)]
    responses = {ROOT + "sitemap.xml": xml("sitemapindex", urls)}
    responses.update({url: xml("sitemapindex", urls) for url in urls})
    fetch = install(monkeypatch, responses)
    assert sitemaps.sitemap_search(ROOT) == []
    assert fetch.call_count == 6


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE urlset [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b"<urlset><url><loc>&xxe;</loc></url></urlset>",
        b'<!DOCTYPE urlset SYSTEM "http://127.0.0.1/internal"><urlset/>',
        b"<not-valid",
    ],
)
def test_hostile_xml_is_rejected_without_followup_fetch(payload, monkeypatch):
    fetch = install(monkeypatch, {ROOT + "sitemap.xml": payload})
    assert sitemaps.sitemap_search(ROOT) == []
    assert fetch.call_count == 2


def test_crawl_uses_final_url_for_relative_links_and_exact_host_scope(monkeypatch):
    root = Page(
        ROOT + "moved/",
        b'<a href="faq#x">FAQ</a><a href="faq#y">Duplicate</a>'
        b'<a href="https://example.com.evil.org/">Other</a>'
        b'<a href="http://127.0.0.1/">Private</a>',
    )
    fetch = Mock(side_effect=[root, Page(ROOT + "moved/faq", b"<p>FAQ</p>")])
    monkeypatch.setattr(website_import, "fetch_page", fetch)
    assert website_import.discover_links_recursively(ROOT) == {ROOT, ROOT + "moved/faq"}
    assert fetch.call_count == 2


def test_crawl_caps_pages_even_with_thousands_of_links(monkeypatch):
    body = "".join(f'<a href="/page-{i}">Page</a>' for i in range(2000)).encode()
    fetch = Mock(side_effect=lambda url: Page(url, body))
    monkeypatch.setattr(website_import, "fetch_page", fetch)
    assert len(website_import.discover_links_recursively(ROOT, max_pages=1000)) == 20
    assert fetch.call_count == 20


def test_crawler_preserves_short_unicode_source_urls(monkeypatch):
    path = "/" + "ż" * 45
    fetch = Mock(side_effect=lambda url: Page(url, f'<a href="{path}">Page</a>'.encode()))
    monkeypatch.setattr(website_import, "fetch_page", fetch)
    urls = website_import.discover_links_recursively(ROOT, max_depth=1)
    assert ROOT.rstrip("/") + path in urls
    assert all(len(url) < 200 for url in urls)


@pytest.mark.parametrize(
    "module,function",
    [
        (sitemaps, sitemaps.sitemap_search),
        (website_import, website_import.discover_links_recursively),
    ],
)
def test_budget_failure_is_not_swallowed_as_an_optional_missing_page(module, function, monkeypatch):
    fetch = Mock(side_effect=FetchLimitExceeded("synthetic budget"))
    monkeypatch.setattr(module, "fetch_page", fetch)
    with pytest.raises(FetchLimitExceeded):
        function(ROOT)
    assert fetch.call_count == 1
