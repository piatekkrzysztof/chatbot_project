import openai
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .models import ChatMessage, Conversation,FAQ
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
import uuid


@csrf_exempt
def chat_with_gpt(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message')
            conversation_id = data.get('conversation_id')

            if not user_message:
                return JsonResponse({'error': 'Brak treści pytania (pole "message").'}, status=400)

            if not conversation_id:
                return JsonResponse({'error': 'Brak conversation_id.'}, status=400)

            conversation, created = Conversation.objects.get_or_create(
                user_identifier=conversation_id
            )

            ChatMessage.objects.create(conversation=conversation,sender="user", message=user_message)

            faqs = FAQ.objects.all()
            faq_questions = [faq.question for faq in faqs]

            match, score=process.extractOne(user_message,faq_questions,scorer=fuzz.token_sort_ratio)

            if score > 75:
                matched_faq = FAQ.objects.get(question=match)
                bot_response = matched_faq.answer
            else:
                client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
                chat_completion = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "Jesteś pomocnym chatbotem obsługującym klientów sklepu internetowego."},
                        {"role": "user", "content": user_message},
                    ],
                    max_tokens=500,
                    temperature=0.7
                )

                bot_response = chat_completion.choices[0].message.content

                ChatMessage.objects.create(conversation=conversation,sender="bot", message=bot_response)

            return JsonResponse({"response": bot_response})

        except Exception as e:
            import traceback
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    return JsonResponse({"error": "Metoda niedozwolona"}, status=405)
