import openai


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
