import logging

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from api.schemas import ErrorSerializer, MessageSerializer, PublicContactRequestSerializer

from api.permissions import IsOwnerOrEmployee
from api.serializers import ContactRequestCreateSerializer, ContactRequestSerializer
from api.utils.mixins import TenantQuerysetMixin
from chat.models import ContactRequest, Conversation

logger = logging.getLogger(__name__)


def notify_owner(contact_request):
    """
    Powiadamia firmę o nowym zapytaniu. Wysyłka nie może wywrócić żądania —
    odwiedzający zostawił dane i musi dostać potwierdzenie niezależnie od SMTP.
    """
    owner_email = contact_request.tenant.owner_email
    if not owner_email:
        return

    try:
        send_mail(
            subject=f"Nowe zapytanie z chatbota ({contact_request.tenant.name})",
            message=(
                f"Ktoś zostawił kontakt w czacie na Twojej stronie.\n\n"
                f"Imię: {contact_request.name or '—'}\n"
                f"Kontakt: {contact_request.contact}\n"
                f"Wiadomość: {contact_request.message or '—'}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[owner_email],
            fail_silently=True,
        )
    except Exception as e:
        logger.warning("Nie udało się wysłać powiadomienia o kontakcie: %s", e)


@extend_schema(
    tags=["Widget"],
    summary="Zostaw kontakt do siebie",
    description="Używane, gdy bot nie potrafi pomóc i proponuje kontakt z firmą.",
    request=PublicContactRequestSerializer,
    responses={201: MessageSerializer, 400: ErrorSerializer},
)
class PublicContactRequestView(APIView):
    """
    Odwiedzający zostawia kontakt, gdy bot nie potrafił pomóc.
    Publiczne — autoryzacja kluczem API widgetu, jak reszta endpointów widgetu.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not getattr(request, "tenant", None):
            raise PermissionDenied("Nieprawidłowy klucz API")

        serializer = ContactRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        conversation = None
        session_id = data.get("conversation_session_id")
        if session_id:
            conversation = Conversation.objects.filter(
                tenant=request.tenant, session_id=session_id
            ).first()

        contact_request = ContactRequest.objects.create(
            tenant=request.tenant,
            conversation=conversation,
            name=data.get("name", ""),
            contact=data["contact"],
            message=data.get("message", ""),
        )
        notify_owner(contact_request)

        return Response({"status": "ok"}, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Panel — zapytania"])
class ContactRequestViewSet(TenantQuerysetMixin,
                            mixins.ListModelMixin,
                            mixins.UpdateModelMixin,
                            viewsets.GenericViewSet):
    """Lista zapytań w panelu; można oznaczyć jako obsłużone."""
    queryset = ContactRequest.objects.all()
    serializer_class = ContactRequestSerializer
    permission_classes = [IsOwnerOrEmployee]
