from rest_framework.test import APITestCase
from django.urls import reverse
from chatbot.models import Tenant


class ChatAPITest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Client",
            api_key="test-key-123",
            gpt_prompt="Odpowiadaj jak ekspert.",
            owner_email="test@example.com"
        )

    def test_chat_view_returns_response(self):
        url = reverse("chat")
        response = self.client.post(
            url,
            {
                "message": "Cześć!",
                "conversation_id": "abc-123"
            },
            HTTP_X_API_KEY=self.tenant.api_key,
            format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_widget_settings(self):
        url = reverse("widget-settings")
        response = self.client.get(url, HTTP_X_API_KEY=self.tenant.api_key)
        self.assertEqual(response.status_code, 200)


class WidgetSettingsTest(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            api_key="test-api-key-001",
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
