import openai
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

@csrf_exempt
def chat_with_gpt(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message')

            if not user_message:
                return JsonResponse({"error": "Brak treści pytania (pole 'message')"}, status=400)

            client = openai.OpenAI(api_key=openai.api_key)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Jesteś pomocnym chatbotem obsługującym klientów sklepu internetowego."},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=500,
                temperature=0.5
            )

            answer = response.choices[0].message.content.strip()

            return JsonResponse({"response": answer})

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def chat_with_gpt(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message')

            if not user_message:
                return JsonResponse({'error': 'Brak treści pytania (pole "message").'}, status=400)

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

            return JsonResponse({"response": bot_response})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({"error": "Metoda niedozwolona"}, status=405)
