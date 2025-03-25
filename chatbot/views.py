import openai
from django.conf import settings
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .models import ChatMessage, Conversation, FAQ, WebsiteSettings
# from fuzzywuzzy import fuzz
# from fuzzywuzzy import process
# import uuid


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
            data = json.loads(request.body)
            user_message = data.get('message')
            conversation_id = data.get('conversation_id')

            if not user_message or not conversation_id:
                return JsonResponse({'error': "Brak wymaganych danych"}, status=400)

            conversation, created = Conversation.objects.get_or_create(
                user_identifier=conversation_id
            )

            website_settings=WebsiteSettings.objects.first()

            if created and website_settings and website_settings.owner_email:
                send_mail(
                    subject='🟢 Nowa rozmowa z chatbotem',
                    message=f'Nowa rozmowa rozpoczęta.\n\nPierwsza wiadomość: "{user_message}"\n\nID rozmowy: {conversation_id}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.OWNER_EMAIL],
                    fail_silently=False,
                )
            ChatMessage.objects.create(
                conversation=conversation, sender="user", message=user_message
            )

            # reuglamin
            if 'regulamin' in user_message.lower():
                bot_response = REGULAMIN
            else:
                faq_context = generate_faq_text()
            prompt = (
                "Otrzymasz teraz pytanie od klienta sklepu internetowego oraz zestaw FAQ. "
                "Twoim zadaniem jest odpowiedzieć na pytanie klienta na podstawie FAQ. "
                "Jeśli FAQ nie zawiera odpowiedzi na pytanie, odpowiedz słowem 'BRAK'.\n\n"
                f"{faq_context}\n\n"
                f"Pytanie klienta: {user_message}\n"
                "Odpowiedź (lub BRAK):"
            )
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            chat_completiton = client.chat.completions.create(
                model='gpt-4o',
                messages=[
                    {"role": "system", "content": "Jesteś chatbotem obsługującym klientów sklepu internetowego."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.0
            )

            bot_response = chat_completiton.choices[0].message.content.strip()

            if bot_response == 'BRAK':
                fallback_completition = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "Jesteś pomocnym chatbotem sklepu internetowego."},
                        {"role": "user", "content": user_message},
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                bot_response = fallback_completition.choices[0].message.content.strip()

            ChatMessage.objects.create(
                conversation=conversation, sender="bot", message=bot_response
            )
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
