import openai
from django.conf import settings

openai.api_key = settings.OPENAI_API_KEY


def get_openai_response(prompt: str, model="gpt-3.5-turbo") -> dict:
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        timeout=15
    )
    content = response['choices'][0]['message']['content']
    tokens = response['usage']['total_tokens']
    return {"content": content, "tokens": tokens}


def count_tokens(text: str) -> int:
    # uproszczony — bez tokenizatora, na oko
    return len(text.split())
