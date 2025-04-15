from celery import shared_task
from documents.models import Document
from documents.utils.embedding_generator import generate_embeddings_for_document
from celery import shared_task
import textract


@shared_task
def embed_document_task(document_id: int):
    from documents.models import Document
    doc = Document.objects.get(id=document_id)
    generate_embeddings_for_document(doc)


@shared_task
def extract_text_from_document(document_id):
    try:
        doc = Document.objects.get(id=document_id)
        if not doc.file:
            return

        text = textract.process(doc.file.path).decode('utf-8')
        doc.content = text
        doc.processed = True
        doc.save()
    except Exception as e:
        # TODO: log to Sentry
        print(f"❌ Błąd przetwarzania dokumentu {document_id}: {e}")