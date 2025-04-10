from celery import shared_task
from documents.models import Document
from documents.utils.embedding_generator import generate_embeddings_for_document


@shared_task
def embed_document_task(document_id: int):
    from documents.models import Document
    doc = Document.objects.get(id=document_id)
    generate_embeddings_for_document(doc)
