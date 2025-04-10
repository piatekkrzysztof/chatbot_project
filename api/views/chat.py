from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from accounts.models import Tenant
from chat.models import Conversation, ChatMessage, ChatUsageLog
from api.serializers import ChatRequestSerializer, ChatResponseSerializer
from rest_framework.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.utils import timezone
from chat.utils import build_prompt, get_openai_response, count_tokens, match_faq_answer
from api.views.throttles import APIKeyRateThrottle


class ChatWithGPTView(APIView):
    throttle_classes = [APIKeyRateThrottle]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        api_key = request.headers.get('X-API-KEY')
        if not api_key:
            raise PermissionDenied("API key missing.")
        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Invalid API key.")

        conversation, _ = Conversation.objects.get_or_create(
            id=data.get('conversation_id'),
            defaults={
                'tenant': tenant,
                'user_identifier': request.META.get("REMOTE_ADDR", "unknown"),
            }
        )

        user_message = data['message'].strip()

        # 🔐 Regulamin (oddzielna logika)
        if user_message.lower() in ['regulamin', 'regulamin.']:
            response_text = tenant.regulamin or "Brak regulaminu"
            ChatMessage.objects.create(
                conversation=conversation,
                sender="bot",
                message=response_text,
                source="manual"
            )
            return Response({"response": response_text})

        # 📥 Zapisz wiadomość użytkownika
        ChatMessage.objects.create(
            conversation=conversation,
            sender="user",
            message=user_message,
            source="manual"
        )

        # 📧 E-mail do właściciela
        send_mail(
            subject=f"Nowy czat – {tenant.name}",
            message=f"Użytkownik napisał: {user_message}",
            from_email="no-reply@yourdomain.com",
            recipient_list=[tenant.owner_email],
            fail_silently=True,
        )

        # 🔍 Fallback #1: Dopasowanie do FAQ
        faq_answer = match_faq_answer(user_message, tenant)
        if faq_answer:
            ChatMessage.objects.create(
                conversation=conversation,
                sender="bot",
                message=faq_answer,
                source="faq"
            )
            return Response({"response": faq_answer})

        # 🔁 Fallback #2: OpenAI GPT
        try:
            prompt = build_prompt(tenant, user_message)
            model = 'gpt-3.5-turbo'
            gpt_response = get_openai_response(prompt, model=model)
            response_text = gpt_response['content']
            token_usage = gpt_response['tokens']
        except Exception:
            response_text = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
            token_usage = 0

        # ✅ Zapisz odpowiedź bota
        ChatMessage.objects.create(
            conversation=conversation,
            sender="bot",
            message=response_text,
            source="gpt",
            token_count=token_usage
        )

        # 📊 Log tokenów
        ChatUsageLog.objects.create(
            tenant=tenant,
            tokens_used=token_usage,
            model_used=model,
            source="gpt",
            conversation=conversation
        )

        return Response({"response": response_text})
