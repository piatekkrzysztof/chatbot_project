from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from accounts.models import Tenant
from documents.utils.pdf_parser import extract_text_from_pdf
from api.serializers import DocumentSerializer
from documents.models import Document
from documents.utils.embedding_generator import generate_embeddings_for_document
from documents.tasks import embed_document_task
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from rest_framework import status


class DocumentDetailView(RetrieveAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [AllowAny]  # lub IsAuthenticated jeśli JWT

    def get_queryset(self):
        api_key = self.request.headers.get("X-API-KEY")
        if not api_key:
            return Document.objects.none()
        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            return Document.objects.none()
        return Document.objects.filter(tenant=tenant)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = DocumentSerializer(instance).data
        data["chunk_count"] = instance.chunks.count()
        data["status"] = "ready" if instance.processed and instance.chunks.exists() else (
            "processing" if not instance.processed else "processed_no_chunks"
        )
        data["preview"] = instance.content[:500] if instance.content else ""
        return Response(data)


class DocumentsViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [AllowAny]  # API key wystarcza

    def get_queryset(self):
        api_key = self.request.headers.get("X-API-KEY")
        if not api_key:
            return Document.objects.none()

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            return Document.objects.none()

        return Document.objects.filter(tenant=tenant).order_by("-uploaded_at")


class UploadDocumentView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return Response({"error": "Missing API Key"}, status=403)

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            return Response({"error": "Invalid API Key"}, status=403)

        file = request.data.get("file")
        name = request.data.get("name") or file.name if file else "Untitled"

        if not file:
            return Response({"error": "No file provided."}, status=400)

        # Wstępny zapis
        document = Document.objects.create(
            tenant=tenant,
            name=name,
            file=file
        )

        # Odczyt treści PDF
        if file.name.lower().endswith(".pdf"):
            text = extract_text_from_pdf(file)
            document.content = text
            document.save()

        # Embeddingi już przez Celery (async)
        embed_document_task.delay(document.id)

        return Response({"message": "Uploaded successfully."}, status=201)
