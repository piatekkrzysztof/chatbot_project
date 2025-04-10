from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from accounts.models import Tenant
from chat.models import Conversation, ChatMessage, ChatUsageLog
from api.serializers import ChatRequestSerializer
from chat.utils import (
    build_prompt,
    get_openai_response,
    match_faq_answer,
    search_documents_chroma
)
from django.core.mail import send_mail
from api.throttles import APIKeyRateThrottle


class ChatWithGPTView(APIView):
    throttle_classes = [APIKeyRateThrottle]

    def post(self, request):
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
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown")
            }
        )

        user_message = data["message"].strip()

        # 1. Regulamin
        if user_message.lower() in ["regulamin", "regulamin."]:
            response_text = tenant.regulamin or "Brak regulaminu"
            ChatMessage.objects.create(
                conversation=conversation,
                sender="bot",
                message=response_text,
                source="manual"
            )
            return Response({"response": response_text})

        # 2. Zapisz pytanie użytkownika
        ChatMessage.objects.create(
            conversation=conversation,
            sender="user",
            message=user_message,
            source="manual"
        )

        # 3. Powiadom właściciela (opcjonalne)
        send_mail(
            subject=f"Nowa wiadomość – {tenant.name}",
            message=f"Użytkownik napisał:\n\n{user_message}",
            from_email="no-reply@yourdomain.com",
            recipient_list=[tenant.owner_email],
            fail_silently=True
        )

        # 4. Fallback 1 – FAQ
        faq_answer = match_faq_answer(user_message, tenant)
        if faq_answer:
            ChatMessage.objects.create(
                conversation=conversation,
                sender="bot",
                message=faq_answer,
                source="faq"
            )
            return Response({"response": faq_answer})

        # 5. Fallback 2 – dokumenty (RAG)
        document_fragments = search_documents_chroma(tenant, user_message)
        if document_fragments:
            rag_context = "\n".join(document_fragments)
            prompt = f"""Na podstawie poniższych informacji z dokumentów klienta, odpowiedz na pytanie użytkownika.

### Dokumenty:
{rag_context}

### Pytanie:
{user_message}
"""
            try:
                model = "gpt-3.5-turbo"
                gpt_response = get_openai_response(prompt, model=model)
                response_text = gpt_response["content"]
                token_usage = gpt_response["tokens"]
            except Exception:
                response_text = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
                token_usage = 0

            ChatMessage.objects.create(
                conversation=conversation,
                sender="bot",
                message=response_text,
                source="document",
                token_count=token_usage
            )

            ChatUsageLog.objects.create(
                tenant=tenant,
                tokens_used=token_usage,
                model_used=model,
                source="document",
                conversation=conversation
            )

            return Response({"response": response_text})

        # 6. Fallback 3 – GPT domyślnie
        try:
            model = "gpt-3.5-turbo"
            prompt = build_prompt(tenant, user_message)
            gpt_response = get_openai_response(prompt, model=model)
            response_text = gpt_response["content"]
            token_usage = gpt_response["tokens"]
        except Exception:
            response_text = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
            token_usage = 0

        ChatMessage.objects.create(
            conversation=conversation,
            sender="bot",
            message=response_text,
            source="gpt",
            token_count=token_usage
        )

        ChatUsageLog.objects.create(
            tenant=tenant,
            tokens_used=token_usage,
            model_used=model,
            source="gpt",
            conversation=conversation
        )

        return Response({"response": response_text})
