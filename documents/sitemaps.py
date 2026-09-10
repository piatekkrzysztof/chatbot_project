"""Small sitemap discovery using the same network policy as page imports."""

from urllib.parse import urljoin, urlsplit, urlunsplit

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from documents.safe_http import (
    _CURRENT_BUDGET,
    FetchError,
    FetchLimitExceeded,
    decompress_gzip,
    fetch_page,
    same_site,
    validate_url,
)

MAX_SITEMAPS = 5
MAX_PAGES = 20


def sitemap_search(base_url):
    base_url = validate_url(base_url)
    parsed = urlsplit(base_url)
    root_url = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
    pending = [urljoin(root_url, "sitemap.xml")]
    scheduled = set(pending)
    pages = []
    seen_pages = set()

    def schedule(value, relative_to):
        if len(scheduled) >= MAX_SITEMAPS:
            return
        try:
            value = validate_url(urljoin(relative_to, value))
        except FetchError:
            return
        if same_site(value, base_url) and value not in scheduled:
            scheduled.add(value)
            pending.append(value)

    try:
        robots = fetch_page(urljoin(root_url, "robots.txt"))
        for line in robots.text.splitlines()[:10000]:
            key, separator, value = line.partition(":")
            if separator and key.strip().lower() == "sitemap":
                schedule(value.strip(), robots.url)
    except FetchLimitExceeded:
        raise
    except FetchError:
        pass  # robots.txt is optional.

    while pending and len(pages) < MAX_PAGES:
        url = pending.pop(0)
        try:
            response = fetch_page(url)
            body = response.body
            if body.startswith(b"\x1f\x8b"):
                body = decompress_gzip(body)
                budget = _CURRENT_BUDGET.get()
                if budget:
                    budget.consume(max(0, len(body) - len(response.body)))
            tree = ElementTree.fromstring(body, forbid_dtd=True)
        except FetchLimitExceeded:
            raise
        except (FetchError, ElementTree.ParseError, DefusedXmlException):
            continue
        kind = tree.tag.rsplit("}", 1)[-1]
        if kind not in {"sitemapindex", "urlset"}:
            continue
        for entry in tree:
            for node in entry:
                if node.tag.rsplit("}", 1)[-1] != "loc" or not node.text:
                    continue
                if kind == "sitemapindex":
                    schedule(node.text.strip(), response.url)
                else:
                    try:
                        page = validate_url(urljoin(response.url, node.text.strip()))
                    except FetchError:
                        continue
                    if same_site(page, base_url) and page not in seen_pages:
                        seen_pages.add(page)
                        pages.append(page)
                if len(pages) >= MAX_PAGES:
                    return pages
    return pages
