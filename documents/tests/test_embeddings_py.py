import pytest
from documents.models import Document, DocumentChunk
from documents.utils.embedding_generator import generate_embeddings_for_document
from accounts.models import Tenant


@pytest.mark.django_db
def test_embeddings_are_generated_for_chunks(mocker):
    tenant = Tenant.objects.create(name="TestOrg", owner_email="admin@t.pl")
    doc = Document.objects.create(
        tenant=tenant,
        name="test",
        content="Ten tekst zostanie podzielony i przetworzony na embeddingi."
    )

    # Mock odpowiedzi OpenAI, żeby nie strzelać do API
    mock_embed = mocker.patch("documents.utils.embedding_generator.client.embeddings.create")
    mock_embed.return_value.data = [type("obj", (object,), {"embedding": [0.1] * 1536})()]

    generate_embeddings_for_document(doc)

    chunks = DocumentChunk.objects.filter(document=doc)
    assert chunks.exists()
    assert chunks.first().embedding is not None
