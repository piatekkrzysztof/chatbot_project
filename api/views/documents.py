from rest_framework import viewsets, permissions
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from api.schemas import DocumentUploadSerializer, ErrorSerializer
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from documents.utils.pdf_parser import extract_text_from_pdf
from documents.validators import sprawdz_limit_bazy_wiedzy
from api.serializers import DocumentSerializer
from documents.models import Document, DocumentChunk, WebsiteSource
from documents.utils.embedding_generator import generate_embeddings_for_document
from documents.tasks import embed_document_task, crawl_and_import_website_source
from documents.utils.queue import enqueue
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.exceptions import ValidationError
from api.serializers import DocumentChunkSerializer, WebsiteSourceSerializer
from api.utils.mixins import TenantQuerysetMixin
from api.permissions import *


class DocumentDetailView(TenantQuerysetMixin, RetrieveAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().order_by("-uploaded_at")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = DocumentSerializer(instance).data
        data["chunk_count"] = instance.chunks.count()
        data["status"] = "ready" if instance.processed and instance.chunks.exists() else (
            "processing" if not instance.processed else "processed_no_chunks"
        )
        data["preview"] = instance.content[:500] if instance.content else ""
        return Response(data)


@extend_schema(tags=["Panel — baza wiedzy"])
class DocumentsViewSet(TenantQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().order_by("-uploaded_at")


@extend_schema(
    tags=["Panel — baza wiedzy"],
    summary="Wgraj dokument",
    description="PDF, DOCX, TXT lub MD. Treść trafia do wyszukiwania po przetworzeniu.",
    request={"multipart/form-data": DocumentUploadSerializer},
    responses={201: DocumentSerializer, 400: ErrorSerializer},
)
class UploadDocumentView(APIView):
    parser_classes = [MultiPartParser]
    permission_classes=[IsOwnerOrEmployee]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"error": "Brak tenanta."}, status=403)

        file = request.data.get("file")
        name = request.data.get("name") or file.name if file else "Untitled"

        if not file:
            return Response({"error": "No file provided."}, status=400)

        # Treść wyodrębniamy przed zapisem, bo bez niej nie da się sprawdzić
        # limitu bazy wiedzy — a dokument zapisany i zaraz usunięty zostawiałby
        # plik w magazynie i zadanie embeddingów w kolejce.
        text = ""
        if file.name.lower().endswith(".pdf"):
            text = extract_text_from_pdf(file)

        sprawdz_limit_bazy_wiedzy(tenant, text)

        document = Document.objects.create(
            tenant=tenant,
            name=name,
            file=file,
            content=text,
        )

        # Embeddingi już przez Celery (async)
        enqueue(embed_document_task, document.id)

        return Response({"message": "Uploaded successfully."}, status=201)


@extend_schema(tags=["Panel — baza wiedzy"], summary="Fragmenty dokumentu w wyszukiwaniu")
class DocumentChunkListView(TenantQuerysetMixin, ListAPIView):
    queryset = DocumentChunk.objects.all()
    serializer_class = DocumentChunkSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return DocumentChunk.objects.filter(document__tenant=self.request.tenant, document_id=self.kwargs["document_id"])


@extend_schema(tags=["Panel — baza wiedzy"])
class WebsiteSourceViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = WebsiteSource.objects.all()
    serializer_class = WebsiteSourceSerializer
    permission_classes = [IsOwnerOrEmployee]

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at")

    def perform_create(self, serializer):
        tenant = self.request.tenant
        url = serializer.validated_data["url"]

        if WebsiteSource.objects.filter(tenant=tenant, url=url).exists():
            raise ValidationError({"url": "Ten adres URL został już dodany."})

        source = serializer.save(tenant=tenant)
        enqueue(crawl_and_import_website_source, source.id)
