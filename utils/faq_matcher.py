def match_faq_answer(user_question: str, tenant) -> str | None:
    """
    Dopasowuje pytanie użytkownika do znanych FAQ tenant'a.
    Zakładamy, że tenant ma listę par (pytanie, odpowiedź) jako pole `faq_pairs`.
    """
    faq_pairs = getattr(tenant, "faq_pairs", [])
    for question, answer in faq_pairs:
        if question.lower() in user_question.lower():
            return answer
    return None