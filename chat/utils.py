import openai

from difflib import SequenceMatcher


def get_openai_response(prompt, model="gpt-3.5-turbo"):
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        timeout=15,
    )
    content = response['choices'][0]['message']['content']
    tokens = response['usage']['total_tokens']
    return {"content": content, "tokens": tokens}


def build_prompt(tenant, message):
    faqs = tenant.faqs.all()
    faq_section = "\n".join([f"- {f.question}: {f.answer}" for f in faqs])
    return f"""
Odpowiadaj jako asystent firmy {tenant.name}.
Dostępne FAQ:\n{faq_section}\n
Użytkownik pyta:\n{message}
"""


def count_tokens(text):
    return len(text.split())


def match_faq_answer(message: str, tenant) -> str | None:
    """Zwraca dopasowaną odpowiedź z FAQ lub None"""
    message = message.lower().strip()
    faqs = tenant.faqs.all()

    best_match = None
    best_score = 0.0

    for faq in faqs:
        score = SequenceMatcher(None, message, faq.question.lower()).ratio()
        if score > best_score:
            best_score = score
            best_match = faq

    if best_score >= 0.85:  # próg dopasowania
        return best_match.answer

    return None
