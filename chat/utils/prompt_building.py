from difflib import SequenceMatcher


def match_faq_answer(message: str, tenant) -> str | None:
    """Dopasowuje pytanie do istniejących FAQ danego tenant'a"""
    message = message.lower().strip()
    faqs = tenant.faqs.all()

    best_match = None
    best_score = 0.0

    for faq in faqs:
        score = SequenceMatcher(None, message, faq.question.lower()).ratio()
        if score > best_score:
            best_score = score
            best_match = faq

    if best_score >= 0.85:
        return best_match.answer

    return None


def build_prompt(tenant, message: str) -> str:
    faqs = tenant.faqs.all()
    faq_section = "\n".join([f"- {f.question}: {f.answer}" for f in faqs])

    return f"""
Jesteś asystentem klienta firmy {tenant.name}.
Masz dostęp do najczęściej zadawanych pytań i udzielasz pomocnych odpowiedzi.

### FAQ:
{faq_section}

### Pytanie użytkownika:
{message}
"""
