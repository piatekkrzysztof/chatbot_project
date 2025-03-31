from django.conf import settings
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
import json

from openai import OpenAI

from .models import ChatMessage, Conversation, FAQ, Tenant, ChatUsageLog


# from fuzzywuzzy import fuzz
# from fuzzywuzzy import process
# import uuid

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

            if 'regulamin' in user_message.lower():
                bot_response = tenant.regulamin
                total_tokens = 0  # brak użycia OpenAI
            else:
                faq_items = FAQ.objects.filter(tenant=tenant)
                faq_text = "\n\n".join([
                    f"Pytanie: {f.question}\nOdpowiedź: {f.answer}" for f in faq_items
                ])

                prompt = (
                    f"{faq_text}\n\nPytanie klienta: {user_message}\n"
                    "Jeśli FAQ nie zawiera odpowiedzi, napisz 'BRAK'."
                )

                openai_key = tenant.openai_api_key or settings.OPENAI_API_KEY
                client = OpenAI(api_key=openai_key)

                chat_completiton = client.chat.completions.create(
                    model='gpt-4o',
                    messages=[
                        {"role": "system", "content": tenant.gpt_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=300,
                    temperature=0.0
                )

                bot_response = chat_completiton.choices[0].message.content.strip()
                total_tokens = chat_completiton.usage.total_tokens

                if bot_response == 'BRAK':
                    fallback_completition = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": tenant.gpt_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        max_tokens=500,
                        temperature=0.7
                    )
                    bot_response = fallback_completition.choices[0].message.content.strip()
                    total_tokens += fallback_completition.usage.total_tokens

            ChatMessage.objects.create(
                conversation=conversation, sender="bot", message=bot_response
            )

            ChatUsageLog.objects.create(tenant=tenant, tokens_used=total_tokens)

            return JsonResponse({"response": bot_response})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({"error": "Metoda niedozwolona"}, status=405)

# @csrf_exempt
# def chat_with_gpt(request):
#     if request.method == 'POST':
#         try:
#             data = json.loads(request.body)
#             user_message = data.get('message')
#             conversation_id = data.get('conversation_id')
#
#             if not user_message:
#                 return JsonResponse({'error': 'Brak treści pytania (pole "message").'}, status=400)
#
#             if not conversation_id:
#                 return JsonResponse({'error': 'Brak conversation_id.'}, status=400)
#
#             conversation, created = Conversation.objects.get_or_create(
#                 user_identifier=conversation_id
#             )
#
#             ChatMessage.objects.create(conversation=conversation,sender="user", message=user_message)
#
#             faqs = FAQ.objects.all()
#             faq_questions = [faq.question for faq in faqs]
#
#             match, score=process.extractOne(user_message,faq_questions,scorer=fuzz.token_sort_ratio)
#
#             if score > 75:
#                 matched_faq = FAQ.objects.get(question=match)
#                 bot_response = matched_faq.answer
#             else:
#                 client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
#                 chat_completion = client.chat.completions.create(
#                     model="gpt-4o",
#                     messages=[
#                         {"role": "system", "content": "Jesteś pomocnym chatbotem obsługującym klientów sklepu internetowego."},
#                         {"role": "user", "content": user_message},
#                     ],
#                     max_tokens=500,
#                     temperature=0.7
#                 )
#
#                 bot_response = chat_completion.choices[0].message.content
#
#                 ChatMessage.objects.create(conversation=conversation,sender="bot", message=bot_response)
#
#             return JsonResponse({"response": bot_response})
#
#         except Exception as e:
#             import traceback
#             return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
#
#     return JsonResponse({"error": "Metoda niedozwolona"}, status=405)
