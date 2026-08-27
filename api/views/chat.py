from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from api.serializers import ChatRequestSerializer
from api.throttles import APIKeyRateThrottle
from api.permissions import IsTenantMember
from drf_spectacular.utils import OpenApiResponse, extend_schema

from api.schemas import PublicChatResponseSerializer
from accounts.models import Tenant
from chat.models import Conversation, ChatMessage, PromptLog, ChatUsageLog
from chat.privacy import visitor_identifier
from api.utils.chat_engine import process_chat_message, split_billing
from accounts.models import Subscription
from rest_framework.throttling import ScopedRateThrottle


@extend_schema(
    tags=["Panel — czat"],
    summary="Zadaj pytanie botowi z panelu",
    description="Odpowiednik endpointu widgetu, ale dla zalogowanego użytkownika.",
    request=ChatRequestSerializer,
    responses={
        200: PublicChatResponseSerializer,
        429: OpenApiResponse(description="Limit planu wyczerpany."),
    },
)
class ChatWithGPTView(APIView):
    throttle_classes = [APIKeyRateThrottle]
    permission_classes = [IsTenantMember]

    def post(self, request):
        subscription = request.subscription
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        tenant = getattr(request, "tenant", None)
        if tenant is None:
            raise PermissionDenied("Brak uprawnień lub nieprawidłowy klucz API.")

        conversation, _ = Conversation.objects.get_or_create(
            session_id=data["conversation_session_id"],
            tenant=tenant,
            defaults={"tenant": tenant, "user_identifier": visitor_identifier(request)},
        )

        user_message = data["message"].strip()

        result = process_chat_message(tenant, conversation, user_message)

        # Awaria modelu nie zjada limitu, za który klient zapłacił
        payload, billable = split_billing(result)
        if billable:
            subscription.increment_usage()

        return Response(payload)
