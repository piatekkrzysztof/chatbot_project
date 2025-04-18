from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.models import Tenant
from api.throttles import APIKeyRateThrottle
from uuid import UUID


class WidgetSettingsAPIView(APIView):
    throttle_classes = [APIKeyRateThrottle]

    def get(self, request):
        api_key = request.headers.get("X-API-KEY")

        if not api_key:
            return Response({"error": "Brak klucza API."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            UUID(api_key, version=4)
        except (ValueError, TypeError):
            return Response({"error": "Nieprawidłowy format klucza API."}, status=status.HTTP_400_BAD_REQUEST)

        tenant = Tenant.objects.filter(api_key=api_key).first()
        if not tenant:
            return Response({"error": "Niepoprawny klucz API"}, status=status.HTTP_403_FORBIDDEN)

        settings_data = {
            "widget_position": tenant.widget_position,
            "widget_color": tenant.widget_color,
            "widget_title": tenant.widget_title,
        }

        return Response(settings_data, status=status.HTTP_200_OK)
