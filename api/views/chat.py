from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from api.serializers import ChatRequestSerializer
from api.throttles import APIKeyRateThrottle
from accounts.models import Tenant
from chat.models import Conversation, ChatMessage, PromptLog, ChatUsageLog
from api.utils.chat_engine import process_chat_message
from accounts.models import Subscription


class ChatWithGPTView(APIView):
    throttle_classes = [APIKeyRateThrottle]

    def post(self, request):
        subscription = request.subscription
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("API key missing.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Invalid API key.")

        conversation, _ = Conversation.objects.get_or_create(
            id=data["conversation_id"],
            tenant=tenant,
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown")
            }
        )

        user_message = data["message"].strip()

        result = process_chat_message(tenant, conversation, user_message)

        subscription.increment_usage()

        return Response(result)
