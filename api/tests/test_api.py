from rest_framework.test import APITestCase
from django.urls import reverse
from accounts.models import Tenant, Subscription
import datetime


class ChatAPITest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Client",
            gpt_prompt="Odpowiadaj jak ekspert.",
            owner_email="test@example.com"
        )
        self.subscription = Subscription.objects.create(
            tenant=Tenant.objects.get(pk=self.tenant.pk),
            plan_type="pro",
            start_date=datetime.date.today() - datetime.timedelta(days=1),
            end_date=datetime.date.today() + datetime.timedelta(days=1),
            is_active=True,
        )
        print("ALL subscriptions for tenant:", Subscription.objects.filter(tenant=self.tenant).values())
        print("ALL tenants:", Tenant.objects.all().values())
        print("Tenant for key:", Tenant.objects.get(api_key=self.tenant.api_key))
        subs = Subscription.objects.filter(tenant=self.tenant)
        print("SUBS found:", subs.count(), list(subs.values()))

    def test_chat_view_returns_response(self):
        url = reverse("chat")
        response = self.client.post(
            url,
            {
                "message": "Cześć!",
                "conversation_id": 1
            },
            HTTP_X_API_KEY=self.tenant.api_key,
            format="json"
        )
        print(">>> [DEBUG] Response status:", response.status_code)
        print(">>> [DEBUG] Response content:", response.content)
        self.assertEqual(response.status_code, 200)

    def test_widget_settings(self):
        url = reverse("widget-settings")
        response = self.client.get(url, HTTP_X_API_KEY=self.tenant.api_key)
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
        response = self.client.get(url, HTTP_X_API_KEY=self.tenant.api_key)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["widget_title"], "Chatbot Test")
