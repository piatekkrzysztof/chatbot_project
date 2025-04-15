from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from api.serializers import ChatRequestSerializer
from api.throttles import APIKeyRateThrottle

from accounts.models import Tenant
from chat.models import ChatMessage, Conversation, ChatUsageLog
from rag.engine import query_similar_chunks_pgvector
from rag.prompter import build_prompt
from utils.openai_client import get_openai_response
from utils.faq_matcher import match_faq_answer
from django.core.mail import send_mail


class ChatWithGPTView(APIView):
    throttle_classes = [APIKeyRateThrottle]

    def post(self, request):
        # 1. Walidacja danych wejściowych
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user_message = data["message"].strip()

        # 2. Autoryzacja tenantów przez X-API-KEY
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("API key missing.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Invalid API key.")

        # 3. Identyfikacja lub tworzenie konwersacji
        conversation, _ = Conversation.objects.get_or_create(
            id=data["conversation_id"],
            defaults={
                "tenant": tenant,
                "user_identifier": request.META.get("REMOTE_ADDR", "unknown")
            }
        )

        # 4. Komenda specjalna: regulamin
        if user_message.lower() in ["regulamin", "regulamin."]:
            response_text = tenant.regulamin or "Brak regulaminu"
            ChatMessage.objects.create(
                conversation=conversation,
                sender="bot",
                message=response_text,
                source="manual"
            )
            return Response({"response": response_text, "source": "manual"})

        # 5. Zapisz wiadomość użytkownika
        ChatMessage.objects.create(
            conversation=conversation,
            sender="user",
            message=user_message,
            source="manual"
        )

        # 6. Powiadom właściciela (jeśli email istnieje)
        if tenant.owner_email:
            send_mail(
                subject=f"Nowa wiadomość – {tenant.name}",
                message=f"Użytkownik napisał:\n\n{user_message}",
                from_email="no-reply@yourdomain.com",
                recipient_list=[tenant.owner_email],
                fail_silently=True
            )

        model = "gpt-3.5-turbo"
        response_text = ""
        token_usage = 0

        # 7. Fallback 1 – dopasowanie do FAQ
        faq_answer = match_faq_answer(user_message, tenant)
        if faq_answer:
            ChatMessage.objects.create(
                conversation=conversation,
                sender="bot",
                message=faq_answer,
                source="faq"
            )
            return Response({"response": faq_answer, "source": "faq"})

        # 8. Fallback 2 – RAG z dokumentów (PGVector)
        try:
            chunks = query_similar_chunks_pgvector(tenant.id, user_message, top_k=5)
        except Exception:
            chunks = []

        if chunks:
            prompt = build_prompt(user_message, chunks)
            try:
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

            return Response({
                "response": response_text,
                "source": "document",
                "model": model
            })

        # 9. Fallback 3 – czysty GPT bez kontekstu
        try:
            gpt_response = get_openai_response(user_message, model=model)
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

        return Response({
            "response": response_text,
            "source": "gpt",
            "model": model
        })
