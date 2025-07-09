import pytest
from django.test import RequestFactory
from accounts.middleware import TenantMiddleware
from accounts.models import Tenant
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_tenant_middleware_assigns_tenant(api_client,user,tenant):
    user.tenant=tenant

    api_client.force_authenticate(user=user)

    factory = RequestFactory()
    request = factory.get("/api/chat/", HTTP_X_API_KEY=str(tenant.api_key))
    request.user = user
    middleware = TenantMiddleware(lambda r: r)
    middleware(request)
    assert hasattr(request, "tenant")
    assert request.tenant == tenant
