from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from api.serializers import ChatRequestSerializer
from api.throttles import APIKeyRateThrottle
from api.permissions import IsTenantMember
from accounts.models import Tenant
from chat.models import Conversation, ChatMessage, PromptLog, ChatUsageLog
from api.utils.chat_engine import process_chat_message
from accounts.models import Subscription
from rest_framework.throttling import ScopedRateThrottle



class ChatWithGPTView(APIView):
    throttle_classes = [ APIKeyRateThrottle]
    permission_classes = [IsTenantMember]

    def post(self, request):
        print(f"[DEBUG widok] request.user: {request.user}")
        print(f"[DEBUG widok] request.tenant: {getattr(request, 'tenant', None)}")
        print(f"[VIEW] request.user: {request.user} | request.tenant: {getattr(request, 'tenant', None)}")
        print(f"Subscription in view: {request.subscription}")
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
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown")
            }
        )

        user_message = data["message"].strip()

        result = process_chat_message(tenant, conversation, user_message)

        subscription.increment_usage()

        return Response(result)
