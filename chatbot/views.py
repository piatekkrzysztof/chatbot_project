from django.conf import settings
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
import json
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

from openai import OpenAI

from .models import ChatMessage, Conversation, FAQ, Tenant, ChatUsageLog

client = chromadb.PersistentClient(path="./chroma_db")


@require_GET
def widget_settings(request):
    api_key = request.headers.get('X-API-KEY')
    tenant = Tenant.objects.filter(api_key=api_key).first()

    if not tenant:
        return JsonResponse({'error': 'Niepoprawny klucz API'}, status=403)

    settings = {
        'widget_position': tenant.widget_position,
        'widget_color': tenant.widget_color,
        'widget_title': tenant.widget_title,
    }

    return JsonResponse(settings)


def generate_faq_text():
    faq_items = FAQ.objects.all()
    faq_text = "FAQ:\n"
    for item in faq_items:
        faq_text += f"Pytanie: {item.question}\nOdpowiedź: {item.answer}"
    return faq_text


REGULAMIN = "DUPA"


def find_relevant_documents(tenant, user_message, top_k=3):
    collection_name = f"tenant_{tenant.id}_documents"

    embedding_function = OpenAIEmbeddingFunction(
        api_key=tenant.openai_api_key or settings.OPENAI_API_KEY,
        model_name="text-embedding-3-small"
    )

    collection = client.get_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

    results = collection.query(
        query_texts=[user_message],
        n_results=top_k
    )

    # Łączymy wyniki w jeden tekst
    relevant_docs = "\n\n".join(results['documents'][0])

    return relevant_docs


@csrf_exempt
def chat_with_gpt(request):
    if request.method == "POST":
        try:
            api_key = request.headers.get('X-API-KEY')
            data = json.loads(request.body)
            user_message = data.get('message')
            conversation_id = data.get('conversation_id')

            if not api_key:
                return JsonResponse({'error': 'Brak klucza API'}, status=403)

            tenant = Tenant.objects.filter(api_key=api_key).first()
            if not tenant:
                return JsonResponse({'error': 'Niepoprawny klucz API'}, status=403)

            conversation, created = Conversation.objects.get_or_create(
                tenant=tenant, user_identifier=conversation_id
            )

            if created:
                send_mail(
                    subject='🟢 Nowy czat rozpoczęty!',
                    message=f'Nowa rozmowa rozpoczęta.\n\nPierwsza wiadomość: "{user_message}"'
                            f'\n\nID rozmowy: {conversation_id}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[tenant.owner_email],
                    fail_silently=False,
                )

            ChatMessage.objects.create(
                conversation=conversation, sender="user", message=user_message
            )

            # Sprawdzamy regulamin
            if 'regulamin' in user_message.lower():
                bot_response = tenant.regulamin
                total_tokens = 0
            else:
                # FAQ
                faq_items = FAQ.objects.filter(tenant=tenant)
                faq_text = "\n\n".join([
                    f"Pytanie: {f.question}\nOdpowiedź: {f.answer}" for f in faq_items
                ])

                # Wyszukaj w embeddingach
                relevant_docs = find_relevant_documents(tenant, user_message)

                prompt = (
                    f"Oto dokumenty klienta:\n\n{relevant_docs}\n\n"
                    f"Oto FAQ:\n\n{faq_text}\n\n"
                    f"Pytanie klienta: {user_message}\n"
                    "Jeśli ani dokumenty, ani FAQ nie zawierają odpowiedzi, napisz 'BRAK'."
                )

                openai_key = tenant.openai_api_key or settings.OPENAI_API_KEY
                client_gpt = OpenAI(api_key=openai_key)

                chat_completion = client_gpt.chat.completions.create(
                    model='gpt-4o',
                    messages=[
                        {"role": "system", "content": tenant.gpt_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=500,
                    temperature=0.0
                )

                bot_response = chat_completion.choices[0].message.content.strip()
                total_tokens = chat_completion.usage.total_tokens

                if bot_response == 'BRAK':
                    fallback_completion = client_gpt.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": tenant.gpt_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        max_tokens=500,
                        temperature=0.7
                    )
                    bot_response = fallback_completion.choices[0].message.content.strip()
                    total_tokens += fallback_completion.usage.total_tokens

            ChatMessage.objects.create(
                conversation=conversation, sender="bot", message=bot_response
            )

            ChatUsageLog.objects.create(tenant=tenant, tokens_used=total_tokens)

            return JsonResponse({"response": bot_response})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({"error": "Metoda niedozwolona"}, status=405)
