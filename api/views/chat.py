from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from api.serializers import ChatRequestSerializer
from api.throttles import APIKeyRateThrottle
from accounts.models import Tenant, Subscription
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
        tenant = getattr(request, "tenant", None)
        if not tenant:
            # (jeśli throttling jest wyłączony i nie masz middleware, musisz pobrać tenant po API key)
            api_key = request.headers.get("X-API-KEY")
            if not api_key:
                raise PermissionDenied("API key missing")
            try:
                tenant = Tenant.objects.get(api_key=api_key)
            except Tenant.DoesNotExist:
                raise PermissionDenied("Invalid API key")

        subscription = (
            Subscription.objects
            .filter(tenant=tenant, is_active=True)
            .order_by("-end_date")
            .first()
        )
        if not subscription:
            raise PermissionDenied("Invalid subscription")

        # Rozpocznij lub pobierz konwersację
        conversation, _ = Conversation.objects.get_or_create(
            id=data["conversation_id"],
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown"),
            },
        )

        user_message = data["message"].strip()

        print("IN VIEW: request.subscription =", getattr(request, "subscription", None))

        # Przetwarzanie wiadomości przez silnik GPT/AI
        result = process_chat_message(tenant, conversation, user_message)

        # Logowanie zużycia (np. liczenie wiadomości do limitów)
        request.subscription.increment_usage()

        return Response(result)
