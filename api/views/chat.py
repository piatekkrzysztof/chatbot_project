from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.core.mail import send_mail
from chatbot.models import ChatMessage, Conversation, FAQ, Tenant, ChatUsageLog
from api.utils.embedding_utils import find_relevant_documents
from openai import OpenAI


class ChatWithGPTView(APIView):
    def post(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return Response({"error": "Brak klucza API"}, status=status.HTTP_403_FORBIDDEN)

        tenant = Tenant.objects.filter(api_key=api_key).first()
        if not tenant:
            return Response({"error": "Nieprawidłowy klucz API"}, status=status.HTTP_403_FORBIDDEN)

        user_message = request.data.get("message")
        conversation_id = request.data.get("conversation_id")

        if not user_message or not conversation_id:
            return Response({"error": "Brak danych."}, status=status.HTTP_400_BAD_REQUEST)

        conversation, created = Conversation.objects.get_or_create(
            tenant=tenant, user_identifier=conversation_id
        )

        if created:
            send_mail(
                subject="🟢 Nowy czat rozpoczęty!",
                message=f"Nowa rozmowa rozpoczęta.\n\nPierwsza wiadomość: \"{user_message}\"",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[tenant.owner_email],
                fail_silently=False,
            )

        ChatMessage.objects.create(conversation=conversation, sender="user", message=user_message)

        if "regulamin" in user_message.lower():
            bot_response = tenant.regulamin
            total_tokens = 0
        else:
            faq_items = FAQ.objects.filter(tenant=tenant)
            faq_text = "\n\n".join(
                [f"Pytanie: {f.question}\nOdpowiedź: {f.answer}" for f in faq_items]
            )

            relevant_docs = find_relevant_documents(tenant, user_message)

            prompt = (
                f"Oto dokumenty klienta:\n\n{relevant_docs}\n\n"
                f"Oto FAQ:\n\n{faq_text}\n\n"
                f"Pytanie klienta: {user_message}\n"
                "Jeśli ani dokumenty, ani FAQ nie zawierają odpowiedzi, napisz 'BRAK'."
            )

            client = OpenAI(api_key=tenant.openai_api_key or settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": tenant.gpt_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.0,
            )

            bot_response = response.choices[0].message.content.strip()
            total_tokens = response.usage.total_tokens

            if bot_response == "BRAK":
                fallback = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": tenant.gpt_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    max_tokens=500,
                    temperature=0.7,
                )
                bot_response = fallback.choices[0].message.content.strip()
                total_tokens += fallback.usage.total_tokens

        ChatMessage.objects.create(conversation=conversation, sender="bot", message=bot_response)
        ChatUsageLog.objects.create(tenant=tenant, tokens_used=total_tokens)

        return Response({"response": bot_response}, status=200)