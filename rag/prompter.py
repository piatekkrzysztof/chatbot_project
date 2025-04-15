from typing import List
from documents.models import DocumentChunk


def build_prompt(user_question: str, chunks: List[DocumentChunk]) -> str:
    """Buduje prompt z pytania użytkownika i najtrafniejszych chunków."""

    context = "\n\n".join(
        f"[Źródło {i + 1}]\n{chunk.content.strip()}"
        for i, chunk in enumerate(chunks)
    )

    prompt = f"""
Jesteś pomocnym asystentem AI. Odpowiadasz tylko na podstawie dostarczonych dokumentów.

DOKUMENTY:
{context}

PYTANIE:
{user_question}

ODPOWIEDŹ:
"""
    return prompt.strip()