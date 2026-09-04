import logging

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployeeOrTenantReadOnly
from api.schemas import ErrorSerializer, MessageSerializer, PublicContactRequestSerializer
from api.serializers import ContactRequestCreateSerializer, ContactRequestSerializer
from api.utils.mixins import TenantQuerysetMixin
from chat.models import ContactRequest, Conversation
from chat.tasks import powiadom_o_zapytaniu_task
from documents.utils.queue import enqueue

logger = logging.getLogger(__name__)


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
        # Zlecamy zamiast wysyłać: odwiedzający nie ma czekać na serwer poczty.
        # enqueue przy braku brokera wykona to na miejscu, więc powiadomienie
        # nie przepada nawet bez działającego workera.
        enqueue(powiadom_o_zapytaniu_task, contact_request.id)

        return Response({"status": "ok"}, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Panel — zapytania"])
class ContactRequestViewSet(
    TenantQuerysetMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """Lista zapytań w panelu; można oznaczyć jako obsłużone."""

    queryset = ContactRequest.objects.all()
    serializer_class = ContactRequestSerializer
    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]
