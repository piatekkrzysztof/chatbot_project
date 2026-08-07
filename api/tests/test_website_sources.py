import pytest
from rest_framework.test import APIClient

from documents.models import WebsiteSource


@pytest.mark.django_db
def test_create_website_source_triggers_crawl(monkeypatch, user, tenant, subscribtion):
    from documents.tasks import crawl_and_import_website_source
    calls = []
    monkeypatch.setattr(crawl_and_import_website_source, "delay", lambda *a, **kw: calls.append(a))

    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/website-sources/",
        {"url": "https://example.com", "name": "https://example.com"},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert response.status_code == 201
    assert WebsiteSource.objects.count() == 1
    source = WebsiteSource.objects.get()
    assert source.tenant == tenant
    assert calls == [(source.id,)]


@pytest.mark.django_db
def test_duplicate_website_source_rejected(monkeypatch, user, tenant, subscribtion):
    from documents.tasks import crawl_and_import_website_source
    monkeypatch.setattr(crawl_and_import_website_source, "delay", lambda *a, **kw: None)

    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    client.force_authenticate(user=user)

    WebsiteSource.objects.create(tenant=tenant, name="Existing", url="https://example.com")

    response = client.post(
        "/api/website-sources/",
        {"url": "https://example.com", "name": "https://example.com"},
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key),
    )

    assert response.status_code == 400
    assert WebsiteSource.objects.count() == 1


@pytest.mark.django_db
def test_website_sources_scoped_to_tenant(user, tenant, subscribtion):
    from .factories import TenantFactory

    other_tenant = TenantFactory()
    WebsiteSource.objects.create(tenant=tenant, name="Mine", url="https://mine.example.com")
    WebsiteSource.objects.create(tenant=other_tenant, name="Other", url="https://other.example.com")

    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    client.force_authenticate(user=user)

    response = client.get("/api/website-sources/", HTTP_X_API_KEY=str(tenant.api_key))

    assert response.status_code == 200
    urls = [item["url"] for item in response.data]
    assert urls == ["https://mine.example.com"]
