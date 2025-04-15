from celery import shared_task
from documents.models import Document
from documents.utils.embedding_generator import generate_embeddings_for_document
from celery import shared_task
import textract
from documents.models import Document, DocumentChunk
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
import textwrap
import os
import chromadb


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


@shared_task
def generate_embeddings_for_document(document_id):
    try:
        document = Document.objects.select_related("tenant").get(id=document_id)
        if not document.content:
            print(f"⚠️ Dokument {document.id} nie zawiera treści.")
            return

        chroma_client = chromadb.Client()
        embedding_function = OpenAIEmbeddingFunction(
            api_key=os.environ.get("OPENAI_API_KEY"),
            model_name="text-embedding-3-small"
        )

        chunks = textwrap.wrap(document.content, width=1500)
        chroma_collection = chroma_client.get_or_create_collection(
            name=f"tenant_{document.tenant.id}",
            embedding_function=embedding_function
        )

        for i, chunk_text in enumerate(chunks):
            chunk_id = f"{document.id}-{i}"
            embedding = embedding_function(chunk_text)
            DocumentChunk.objects.create(
                document=document,
                content=chunk_text,
                embedding=embedding  # przekazujesz listę floatów
            )

            # zapis do Chroma
            chroma_collection.add(
                ids=[chunk_id],
                documents=[chunk_text],
                metadatas=[{
                    "tenant_id": document.tenant.id,
                    "document_id": document.id,
                    "chunk_index": i,
                }]
            )

        print(
            f"✅ Wygenerowano {len(chunks)} embeddingów dla dokumentu {document.name} (tenant: {document.tenant.name})")

    except Exception as e:
        print(f"❌ Błąd podczas generowania embeddingów dla dokumentu {document_id}: {e}")
