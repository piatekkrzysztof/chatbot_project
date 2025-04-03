from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.models import Tenant


class WidgetSettingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        api_key = request.headers.get('X-API-KEY')
        tenant = Tenant.objects.filter(api_key=api_key).first()

        if not tenant:
            return Response({'error': 'Niepoprawny klucz API'}, status=403)

        settings = {
            'widget_position': tenant.widget_position,
            'widget_color': tenant.widget_color,
            'widget_title': tenant.widget_title,
        }

        return Response(settings, status=200)