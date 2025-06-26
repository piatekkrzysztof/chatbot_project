import pytest
from rest_framework.test import APIClient
from django.utils import timezone
from chat.models import PromptLog
from accounts.models import Tenant
from documents.models import Document, DocumentChunk

@pytest.mark.django_db
def test_prompt_log_created_after_rag(monkeypatch,user, tenant, subscribtion):
    # Mock funkcji get_openai_response
    monkeypatch.setattr("utils.openai_client.get_openai_response", lambda prompt, model: {
        "content": "Odpowiedź testowa",
        "tokens": 123
    })

    # Mock PGVector query – zwracamy 1 chunk
    monkeypatch.setattr("rag.engine.query_similar_chunks_pgvector", lambda tenant_id, query, top_k=5: [
        DocumentChunk(content="To jest przykładowy chunk.")
    ])

    client = APIClient()
    user.tenant = tenant
    user.role = "owner"
    user.save()
    tenant.save()
    client.force_authenticate(user=user)
    document = Document.objects.create(name="Test Doc", tenant=tenant, content="abc")
    client = APIClient()

    res = client.post(
        "/api/chat/",
        {
            "message": "Jak wygląda polityka prywatności?",
            "conversation_id": 1
        },
        format="json",
        HTTP_X_API_KEY=str(tenant.api_key)
    )

    assert res.status_code == 200
    assert PromptLog.objects.count() == 1

    prompt_entry = PromptLog.objects.first()
    assert prompt_entry.source == "document"
    assert "DOKUMENTY" in prompt_entry.prompt
    assert "Jak wygląda polityka" in prompt_entry.prompt
    assert prompt_entry.tokens == 123
    assert prompt_entry.model == "gpt-3.5-turbo"
