from chat.models import ChatMessage, PromptLog, ChatUsageLog
from utils.openai_client import get_openai_response
from utils.faq_matcher import match_faq_answer
from rag.engine import query_similar_chunks_pgvector
from rag.prompter import build_prompt
from django.core.mail import send_mail


def process_chat_message(tenant, conversation, user_message):
    # 1. REGULAMIN
    if user_message.lower() in ["regulamin", "regulamin."]:
        return handle_manual_rule(tenant, conversation)

    # 2. Zapisz wiadomość użytkownika
    ChatMessage.objects.create(
        conversation=conversation,
        sender="user",
        message=user_message,
        source="manual"
    )

    # 3. Powiadom właściciela
    if tenant.owner_email:
        send_mail(
            subject=f"Nowa wiadomość – {tenant.name}",
            message=f"Użytkownik napisał:\n\n{user_message}",
            from_email="no-reply@yourdomain.com",
            recipient_list=[tenant.owner_email],
            fail_silently=True
        )

    # 4. Fallback 1 – FAQ
    faq_answer = match_faq_answer(user_message, tenant)
    if faq_answer:
        return handle_bot_response(conversation, faq_answer, "faq", tenant)

    # 5. Fallback 2 – Dokumenty (RAG)
    try:
        chunks = query_similar_chunks_pgvector(tenant.id, user_message, top_k=5)
    except Exception:
        chunks = []

    if chunks:
        prompt = build_prompt(user_message, chunks)
        try:
            gpt_response = get_openai_response(prompt)
            return handle_gpt_response(conversation, tenant, gpt_response, "document", prompt)
        except Exception:
            return handle_error_response(conversation, "document")

    # 6. Fallback 3 – GPT (bez dokumentów)
    try:
        prompt = build_prompt(tenant, user_message)
        gpt_response = get_openai_response(prompt)
        return handle_gpt_response(conversation, tenant, gpt_response, "gpt", prompt)
    except Exception:
        return handle_error_response(conversation, "gpt")


def handle_manual_rule(tenant, conversation):
    response_text = tenant.regulamin or "Brak regulaminu"
    ChatMessage.objects.create(
        conversation=conversation,
        sender="bot",
        message=response_text,
        source="manual"
    )
    return {"response": response_text, "source": "manual"}


def handle_bot_response(conversation, text, source, tenant):
    ChatMessage.objects.create(
        conversation=conversation,
        sender="bot",
        message=text,
        source=source
    )
    return {"response": text, "source": source}


def handle_gpt_response(conversation, tenant, gpt_response, source, prompt):
    content = gpt_response["content"]
    tokens = gpt_response.get("tokens", 0)
    model = gpt_response.get("model", "gpt-3.5-turbo")

    ChatMessage.objects.create(
        conversation=conversation,
        sender="bot",
        message=content,
        source=source,
        token_count=tokens
    )

    ChatUsageLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        tokens_used=tokens,
        model_used=model,
        source=source
    )

    PromptLog.objects.create(
        tenant=tenant,
        conversation=conversation,
        prompt=prompt,
        response=content,
        tokens=tokens,
        model=model,
        source=source
    )

    return {
        "response": content,
        "source": source,
        "model": model,
        "tokens_used": tokens
    }


def handle_error_response(conversation, source):
    fallback = "Wystąpił błąd po stronie modelu. Spróbuj ponownie później."
    ChatMessage.objects.create(
        conversation=conversation,
        sender="bot",
        message=fallback,
        source=source
    )
    return {"response": fallback, "source": source}
