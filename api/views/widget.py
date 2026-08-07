from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.models import Tenant
from api.throttles import APIKeyRateThrottle
from uuid import UUID
from rest_framework.exceptions import PermissionDenied
from chat.models import FAQ, Conversation
from api.serializers import PublicFAQSerializer, ChatRequestSerializer
from api.utils.chat_engine import process_chat_message, stream_chat_message
from api.permissions import IsOwnerOrEmployee
from django.http import StreamingHttpResponse



def serialize_widget_branding(tenant, request):
    return {
        "widget_position": tenant.widget_position,
        "widget_color": tenant.widget_color,
        "widget_title": tenant.widget_title,
        "branding_mode": tenant.branding_mode,
        "widget_footer_text": tenant.widget_footer_text,
        "widget_logo": request.build_absolute_uri(tenant.widget_logo.url) if tenant.widget_logo else None,
        "widget_avatar": request.build_absolute_uri(tenant.widget_avatar.url) if tenant.widget_avatar else None,
    }


class WidgetSettingsAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        if not getattr(request, "tenant", None):
            return Response({"error": "Brak poprawnego klucza API"}, status=403)
        return Response(serialize_widget_branding(request.tenant, request), status=status.HTTP_200_OK)


class PublicFAQView(APIView):
    authentication_classes = []  # brak JWT
    permission_classes = []  # walidacja przez API key (X-API-KEY), wykonana w TenantMiddleware

    def get(self, request):
        if not getattr(request, "tenant", None):
            raise PermissionDenied("Nieprawidłowy klucz API")

        faqs = FAQ.objects.filter(tenant=request.tenant).order_by("id")
        serializer = PublicFAQSerializer(faqs, many=True)
        return Response(serializer.data)


class PublicChatView(APIView):
    """
    Publiczny endpoint czatu dla osadzalnego widgetu — autoryzacja przez
    X-API-Key (request.tenant/request.subscription ustawiane przez middleware),
    bez logowania JWT. Odpowiednik ChatWithGPTView dla anonimowych odwiedzających
    stronę klienta.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not getattr(request, "tenant", None):
            raise PermissionDenied("Nieprawidłowy klucz API")

        subscription = getattr(request, "subscription", None)

        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = request.tenant

        conversation, _ = Conversation.objects.get_or_create(
            session_id=data["conversation_session_id"],
            tenant=tenant,
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown"),
                "source": "widget",
            }
        )

        result = process_chat_message(tenant, conversation, data["message"].strip())

        if subscription:
            subscription.increment_usage()

        return Response(result)


class PublicChatStreamView(APIView):
    """
    Strumieniowa wersja PublicChatView — odpowiedź leci token po tokenie (SSE),
    dzięki czemu użytkownik widzi ją od razu zamiast czekać na całość.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not getattr(request, "tenant", None):
            raise PermissionDenied("Nieprawidłowy klucz API")

        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = request.tenant

        conversation, _ = Conversation.objects.get_or_create(
            session_id=data["conversation_session_id"],
            tenant=tenant,
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown"),
                "source": "widget",
            }
        )

        # Limit odliczamy z góry — po rozpoczęciu strumienia nie da się już odrzucić żądania.
        subscription = getattr(request, "subscription", None)
        if subscription:
            subscription.increment_usage()

        response = StreamingHttpResponse(
            stream_chat_message(tenant, conversation, data["message"].strip()),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # wyłącza buforowanie na nginx/proxy
        return response


class TenantWidgetSettingsView(APIView):
    """
    Uwierzytelniony (JWT) branding widgetu dla panelu klienta —
    odpowiednik WidgetSettingsAPIView, ale do odczytu/zapisu przez właściciela,
    nie do publicznego odczytu przez sam widget.
    """
    permission_classes = [IsOwnerOrEmployee]

    def get(self, request):
        return Response(serialize_widget_branding(request.user.tenant, request))

    def patch(self, request):
        tenant = request.user.tenant
        text_fields = ("widget_position", "widget_color", "widget_title", "branding_mode", "widget_footer_text")
        changed_fields = []

        for field in text_fields:
            if field in request.data:
                setattr(tenant, field, request.data[field])
                changed_fields.append(field)

        for file_field in ("widget_logo", "widget_avatar"):
            if file_field in request.FILES:
                setattr(tenant, file_field, request.FILES[file_field])
                changed_fields.append(file_field)

        if changed_fields:
            tenant.save(update_fields=changed_fields)

        return Response(serialize_widget_branding(tenant, request))
