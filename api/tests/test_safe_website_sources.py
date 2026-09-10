"""Adres wewnętrzny ma zostać odrzucony, zanim trafi do kolejki lub sieci."""

from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from api.serializers import WebsiteSourceSerializer
from documents.models import Document, WebsiteSource
from documents.tasks import crawl_and_import_website_source
from documents.website_import import fetch_text_from_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://[fd00::1]/",
        "http://[::ffff:127.0.0.1]/",
        "https://user:password@example.com/",
        "http://example.com:6379/",
        "ftp://example.com/file",
    ],
)
def test_serializer_rejects_unsafe_website_source(url):
    serializer = WebsiteSourceSerializer(data={"url": url, "name": "Strona"})
    assert not serializer.is_valid(), serializer.validated_data
    assert "url" in serializer.errors


def test_single_page_fetch_rejects_loopback_before_downloader(monkeypatch):
    download = Mock(
        return_value="<html><body><p>" + "Ważna treść strony. " * 50 + "</p></body></html>"
    )
    monkeypatch.setattr("trafilatura.fetch_url", download)
    with pytest.raises(ValueError):
        fetch_text_from_url("http://127.0.0.1/private")
    download.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "ftp://example.com/"])
def test_api_rejects_unsafe_source_without_saving_or_scheduling(
    url, monkeypatch, user, tenant, subscribtion
):
    schedule = Mock()
    monkeypatch.setattr(crawl_and_import_website_source, "delay", schedule)
    user.tenant = tenant
    user.role = "owner"
    user.save()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    response = client.post("/api/website-sources/", {"url": url, "name": "Unsafe"}, format="json")
    assert response.status_code == 400
    assert "url" in response.data
    assert not WebsiteSource.objects.filter(tenant=tenant).exists()
    schedule.assert_not_called()


@pytest.mark.django_db
def test_legacy_internal_source_fails_without_touching_network(monkeypatch, tenant):
    source = WebsiteSource.objects.create(tenant=tenant, url="http://127.0.0.1/", name="Legacy")
    connect = Mock(side_effect=AssertionError("No network expected"))
    monkeypatch.setattr("documents.safe_http.socket.create_connection", connect)
    crawl_and_import_website_source(source.id)
    source.refresh_from_db()
    assert source.last_attempt_at is not None
    assert source.last_crawled_at is None
    assert source.last_error
    assert not Document.objects.filter(tenant=tenant).exists()
    connect.assert_not_called()


@pytest.mark.django_db
def test_task_filters_host_prefix_attack_but_accepts_sibling_paths(monkeypatch, tenant):
    source = WebsiteSource.objects.create(tenant=tenant, url="https://example.com/start")
    import_page = Mock()
    monkeypatch.setattr("documents.tasks.import_website_as_document", import_page)
    monkeypatch.setattr(
        "documents.tasks.sitemap_search",
        lambda url: [
            "https://example.com.evil.org/start",
            "https://example.com/faq",
        ],
    )
    crawl_and_import_website_source(source.id)
    import_page.assert_called_once_with(
        tenant=tenant, url="https://example.com/faq", name="https://example.com/faq"
    )
    source.refresh_from_db()
    assert source.last_error == ""


@pytest.mark.django_db
def test_task_does_not_report_success_when_every_link_is_outside_site(monkeypatch, tenant):
    source = WebsiteSource.objects.create(tenant=tenant, url="https://example.com")
    monkeypatch.setattr(
        "documents.tasks.sitemap_search", lambda url: ["https://example.com.evil.org/"]
    )
    crawl_and_import_website_source(source.id)
    source.refresh_from_db()
    assert source.last_crawled_at is None
    assert source.last_error


@pytest.mark.django_db
def test_refresh_preserves_original_root_spelling_without_duplicate_document(monkeypatch, tenant):
    from documents.safe_http import Page, validate_url
    from documents.utils.tresc_strony import TrescStrony

    url = "https://example.com"  # An existing record without a trailing slash.
    source = WebsiteSource.objects.create(tenant=tenant, url=url)
    original = Document.objects.create(
        tenant=tenant, source="website", source_url=url, name="Existing", content="Old"
    )
    monkeypatch.setattr("documents.tasks.sitemap_search", lambda url: [])
    monkeypatch.setattr(
        "documents.website_import.fetch_page",
        lambda url: Page(validate_url(url), b"<p>No links</p>"),
    )
    monkeypatch.setattr(
        "documents.website_import.fetch_text_from_url", lambda url: TrescStrony("New content", 11)
    )
    crawl_and_import_website_source(source.id)
    original.refresh_from_db()
    assert Document.objects.filter(tenant=tenant).count() == 1
    assert original.content == "New content"
    assert original.source_url == url
