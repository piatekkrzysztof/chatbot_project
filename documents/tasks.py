from documents.utils.embedding_generator import generate_embeddings_for_document
from celery import shared_task
import textract
from documents.models import Document, DocumentChunk, WebsiteSource
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from documents.website_import import discover_links_recursively
import textwrap
import os
import chromadb
from documents.models import WebsiteSource, Document
from documents.website_import import import_website_as_document
import trafilatura


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

            # 🛠️ Naprawa problemu: pgvector wymaga 1D listy floatów
            if isinstance(embedding, list) and len(embedding) == 1:
                embedding = embedding[0]
            elif hasattr(embedding, 'shape') and len(embedding.shape) == 2:
                embedding = embedding[0]
            elif not isinstance(embedding, list):
                raise ValueError("Unsupported embedding format")

            DocumentChunk.objects.create(
                document=document,
                content=chunk_text,
                embedding=embedding
            )

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


@shared_task
def crawl_and_import_website_source(source_id):
    try:
        source = WebsiteSource.objects.select_related("tenant").get(id=source_id)
        url = source.url
        tenant = source.tenant

        # pobierz wszystkie podstrony z sitemap

        urls = trafilatura.sitemaps.sitemap_search(source.url) or []
        if not urls:
            urls = discover_links_recursively(source.url, max_depth=2)

        if not urls:
            urls = [url]  # fallback – tylko główna strona

        for suburl in urls:
            if not suburl.startswith(url):  # zabezpieczenie przed ucieczką poza domenę
                continue

            # sprawdź, czy dokument już istnieje
            if Document.objects.filter(tenant=tenant, source="website", name=suburl).exists():
                continue

            try:
                import_website_as_document(tenant=tenant, url=suburl, name=suburl)
            except Exception as e:
                print(f"⚠️ Błąd podczas importu {suburl}: {e}")

        print(f"✅ Zakończono crawling {url} (source_id={source_id})")

    except WebsiteSource.DoesNotExist:
        print(f"❌ Nie znaleziono WebsiteSource z ID {source_id}")


@shared_task
def crawl_all_active_sources():
    sources = WebsiteSource.objects.filter(is_active=True)
    for source in sources:
        crawl_and_import_website_source.delay(source.id)
