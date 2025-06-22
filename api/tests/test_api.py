from datetime import timedelta

from rest_framework.test import APITestCase
from django.urls import reverse
from accounts.models import Tenant, Subscription
from django.utils import timezone
from django.test import override_settings
import os
import uuid


@override_settings(REST_FRAMEWORK={"DEFAULT_THROTTLE_CLASSES": []})
class ChatAPITest(APITestCase):
    def setUp(self):
        print("==== ACTIVE DJANGO SETTINGS MODULE:", os.environ.get("DJANGO_SETTINGS_MODULE"))
        self.tenant = Tenant.objects.create(
            name="Test Client",
            gpt_prompt="Odpowiadaj jak ekspert.",
            owner_email="test@example.com"
        )
        self.subscription = Subscription.objects.create(
            tenant=self.tenant,
            plan_type="pro",
            start_date=timezone.now().date() - timedelta(days=2),
            end_date=timezone.now().date(),
            is_active=True,
        )
        print("ALL subscriptions for tenant:", Subscription.objects.filter(tenant=self.tenant).values())
        print("ALL tenants:", Tenant.objects.all().values())
        print("Tenant for key:", Tenant.objects.get(api_key=self.tenant.api_key))
        subs = Subscription.objects.filter(tenant=self.tenant)
        print("SUBS found:", subs.count(), list(subs.values()))

    def test_chat_view_returns_response(self):
        url = reverse('chat')
        print(url)
        response = self.client.post(
            url,
            {
                "message": "Cześć!",
                "conversation_id": str(uuid.uuid4())
            },
            HTTP_X_API_KEY=self.tenant.api_key,
            format="json"
        )
        print("TEST DEBUG:", hasattr(response.wsgi_request, "subscription"),
              getattr(response.wsgi_request, "subscription", None))
        print(">>> [DEBUG] Response status:", response.status_code)
        print(">>> [DEBUG] Response content:", response.content)
        self.assertEqual(response.status_code, 200)

    def test_widget_settings(self):
        url = reverse("widget-settings")
        response = self.client.get(url, HTTP_X_API_KEY=str(self.tenant.api_key))
        self.assertEqual(response.status_code, 200)


class WidgetSettingsTest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            widget_position="bottom-right",
            widget_color="#3b82f6",
            widget_title="Chatbot Test",
            owner_email="test@example.com",
            gpt_prompt="Test prompt",
            regulamin="Test regulamin"
        )

    def test_widget_settings(self):
        url = reverse("widget-settings")
        response = self.client.get(url, HTTP_X_API_KEY=str(self.tenant.api_key))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["widget_title"], "Chatbot Test")
