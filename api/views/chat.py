from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from api.serializers import ChatRequestSerializer
from api.throttles import APIKeyRateThrottle
from accounts.models import Tenant
from chat.models import Conversation, ChatMessage, PromptLog, ChatUsageLog
from api.utils.chat_engine import process_chat_message

class ChatWithGPTView(APIView):
    throttle_classes = [APIKeyRateThrottle]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Autoryzacja po kluczu API obsługiwana w throttlingu,
        # request.tenant oraz request.subscription są już ustawione

        # Ostateczna weryfikacja subskrypcji
        if not hasattr(request, "subscription") or request.subscription is None:
            raise PermissionDenied("Invalid subscription")

        tenant = request.tenant

        # Rozpocznij lub pobierz konwersację
        conversation, _ = Conversation.objects.get_or_create(
            id=data["conversation_id"],
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown"),
            },
        )

        user_message = data["message"].strip()

        # Przetwarzanie wiadomości przez silnik GPT/AI
        result = process_chat_message(tenant, conversation, user_message)

        # Logowanie zużycia (np. liczenie wiadomości do limitów)
        request.subscription.increment_usage()

        return Response(result)
