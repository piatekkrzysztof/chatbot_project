from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.models import Tenant
from api.throttles import APIKeyRateThrottle
from uuid import UUID
from rest_framework.exceptions import PermissionDenied
from chat.models import Client, FAQ
from api.serializers import PublicFAQSerializer



class WidgetSettingsAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        print("DEBUG WIDOK: tenant=", getattr(request, "tenant", None))
        if not getattr(request, "tenant", None):
            print("DEBUG WIDOK: BRAK TENANTA, ZWRACAM 403!")
            return Response({"error": "Brak poprawnego klucza API"}, status=403)
        print("DEBUG WIDOK: TENANT JEST, ZWRACAM 200!")
        tenant = request.tenant
        return Response({
            "widget_position": tenant.widget_position,
            "widget_color": tenant.widget_color,
            "widget_title": tenant.widget_title,
        }, status=status.HTTP_200_OK)


class PublicFAQView(APIView):
    authentication_classes = []  # brak JWT
    permission_classes = []  # walidacja przez API key (X-API-KEY)

    def get(self, request):
        api_key = request.headers.get("X-API-KEY")

        if not api_key:
            raise PermissionDenied("Brak nagłówka X-API-KEY")

        try:
            client = Client.objects.select_related("tenant").get(session_id=api_key)
        except Client.DoesNotExist:
            raise PermissionDenied("Nieprawidłowy klucz API")

        faqs = FAQ.objects.filter(tenant=client.tenant).order_by("id")
        serializer = PublicFAQSerializer(faqs, many=True)
        return Response(serializer.data)
