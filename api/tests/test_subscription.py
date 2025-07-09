import pytest
from django.test import RequestFactory
from accounts.middleware import SubscriptionMiddleware
from accounts.models import Tenant, Subscription, CustomUser
from datetime import datetime, timedelta
from django.utils import timezone


@pytest.mark.django_db
def test_subscription_middleware_assigns_subscription(tenant,user,subscribtion):
    factory = RequestFactory()
    request = factory.get("/api/chat/", HTTP_X_API_KEY=str(tenant.api_key))
    request.user = user
    middleware = SubscriptionMiddleware(lambda r: r)
    middleware(request)
    assert hasattr(request, "subscription")
    assert request.subscription == subscribtion



@pytest.mark.django_db
def test_increment_usage(tenant,user,subscribtion):
    assert subscribtion.current_message_count == 0
    subscribtion.increment_usage()
    assert subscribtion.current_message_count == 1


@pytest.mark.django_db
def test_reset_usage_on_new_month(tenant,user,subscribtion):
    subscribtion.current_message_count = 42
    subscribtion.billing_cycle_start = timezone.now().date() - timedelta(days=35)
    subscribtion.save(update_fields=["current_message_count", "billing_cycle_start"])

    subscribtion.reset_usage()

    assert subscribtion.current_message_count == 0
    assert subscribtion.billing_cycle_start == timezone.now().date()

@pytest.mark.django_db
def test_has_message_quota(subscribtion):
    subscribtion.current_message_count = subscribtion.message_limit - 1
    subscribtion.save()
    assert subscribtion.has_message_quota() is True

    subscribtion.current_message_count = subscribtion.message_limit
    subscribtion.save()
    assert subscribtion.has_message_quota() is False