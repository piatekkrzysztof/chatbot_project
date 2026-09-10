import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import storages
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, Http404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import *
from api.schemas import DocumentUploadSerializer, ErrorSerializer, MessageSerializer
from api.serializers import DocumentChunkSerializer, DocumentSerializer, WebsiteSourceSerializer
from api.utils.mixins import TenantQuerysetMixin

# Ta sama zasada odczytu wartości logicznej co w ustawieniach widgetu:
# formularz multipart przysyła "true"/"false" jako tekst.
from api.views.widget import _wlaczone
from chatbot_project.storage import UnconfiguredPrivateStorage
from documents.file_limits import InvalidUpload, UploadTooLarge
from documents.isolated_parser import ParserUnavailable, parse_document
from documents.models import Document, DocumentChunk, WebsiteSource
from documents.tasks import crawl_and_import_website_source
from documents.uploads import LimitedMultiPartParser
from documents.utils.queue import enqueue
from documents.validators import sprawdz_limit_bazy_wiedzy

logger = logging.getLogger(__name__)


class DocumentDetailView(TenantQuerysetMixin, RetrieveAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().order_by("-uploaded_at")


@extend_schema(tags=["Panel — baza wiedzy"])
class DocumentsViewSet(TenantQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().order_by("-uploaded_at")

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        document = self.get_object()
        if not document.file:
            raise Http404
        try:
            handle = document.file.open("rb")
        except FileNotFoundError as error:
            raise Http404 from error
        except ImproperlyConfigured:
            return Response({"error": "Prywatny magazyn dokumentów jest niedostępny."}, status=503)
        response = FileResponse(
            handle,
            as_attachment=True,
            filename=document.name,
            content_type="application/octet-stream",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox"
        return response

    @extend_schema(
        tags=["Panel — baza wiedzy"],
        summary="Włącz lub wyłącz dokument w wyszukiwaniu",
        description=(
            "Wyłączony dokument zostaje w bazie wiedzy, ale bot z niego nie "
            "korzysta. Fragmenty nie są kasowane, więc włączenie z powrotem "
            "działa od razu i nie kosztuje ponownego liczenia wektorów."
        ),
        request=None,
        responses=DocumentSerializer,
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path="wyszukiwanie",
        permission_classes=[IsOwnerOrEmployee],
    )
    def przelacz_wyszukiwanie(self, request, pk=None):
        """
        Osobna akcja zamiast zwykłego PATCH na całym obiekcie.

        To jedyne pole dokumentu, które klient ma prawo zmieniać. Otwarcie
        całego zasobu do zapisu pozwoliłoby podmienić treść albo nazwę bez
        przeliczenia fragmentów — bot odpowiadałby wtedy z wektorów
        policzonych dla czegoś innego, niż widać w panelu.
        """
        dokument = self.get_object()
        wartosc = request.data.get("uzywaj_w_wyszukiwaniu")
        if wartosc is None:
            raise ValidationError({"uzywaj_w_wyszukiwaniu": "Pole jest wymagane."})

        dokument.uzywaj_w_wyszukiwaniu = _wlaczone(wartosc)
        dokument.save(update_fields=["uzywaj_w_wyszukiwaniu"])
        return Response(DocumentSerializer(dokument).data)


@extend_schema(
    tags=["Panel — baza wiedzy"],
    summary="Wgraj dokument",
    description="PDF, DOCX, TXT lub MD. Treść trafia do wyszukiwania po przetworzeniu.",
    request={"multipart/form-data": DocumentUploadSerializer},
    responses={
        201: MessageSerializer,
        400: ErrorSerializer,
        413: ErrorSerializer,
        503: ErrorSerializer,
    },
)
class UploadDocumentView(APIView):
    parser_classes = [LimitedMultiPartParser]
    permission_classes = [IsOwnerOrEmployee]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"error": "Brak tenanta."}, status=403)

        file = request.data.get("file")
        if not isinstance(file, UploadedFile):
            return Response({"error": "No file provided."}, status=400)
        name = request.data.get("name") or file.name

        if not isinstance(name, str) or len(name) > 255:
            return Response({"error": "Nazwa dokumentu może mieć do 255 znaków."}, status=400)

        if isinstance(storages["private_documents"], UnconfiguredPrivateStorage):
            return Response(
                {"error": "Magazyn dokumentów nie jest skonfigurowany. Skontaktuj się z obsługą."},
                status=503,
            )

        # Treść wyodrębniamy przed zapisem, bo bez niej nie da się sprawdzić
        # limitu bazy wiedzy — a dokument zapisany i zaraz usunięty zostawiałby
        # plik w magazynie i zadanie embeddingów w kolejce.
        try:
            text = parse_document(file, file.name, settings.DOCUMENT_MAX_UPLOAD_BYTES)
        except ParserUnavailable as error:
            return Response({"error": str(error)}, status=503)
        except UploadTooLarge as error:
            return Response({"error": str(error)}, status=413)
        except InvalidUpload as error:
            return Response({"error": str(error)}, status=400)
        if not text:
            return Response(
                {"error": "Nie znaleziono tekstu w pliku. Dla skanu najpierw wykonaj OCR."},
                status=400,
            )

        sprawdz_limit_bazy_wiedzy(tenant, text)

        Document.objects.create(
            tenant=tenant,
            name=name,
            file=file,
            content=text,
            processed=True,
        )

        # The post_save signal schedules embeddings once. The file is already
        # parsed, so it must not schedule a second extraction or duplicate embedding job.

        return Response({"message": "Uploaded successfully."}, status=201)


@extend_schema(tags=["Panel — baza wiedzy"], summary="Fragmenty dokumentu w wyszukiwaniu")
class DocumentChunkListView(TenantQuerysetMixin, ListAPIView):
    queryset = DocumentChunk.objects.all()
    serializer_class = DocumentChunkSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return DocumentChunk.objects.filter(
            document__tenant=self.request.tenant, document_id=self.kwargs["document_id"]
        )


@extend_schema(tags=["Panel — baza wiedzy"])
class WebsiteSourceViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = WebsiteSource.objects.all()
    serializer_class = WebsiteSourceSerializer
    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]

    def get_queryset(self):
        return super().get_queryset().order_by("-created_at")

    def perform_create(self, serializer):
        tenant = self.request.tenant
        url = serializer.validated_data["url"]

        if WebsiteSource.objects.filter(tenant=tenant, url=url).exists():
            raise ValidationError({"url": "Ten adres URL został już dodany."})

        source = serializer.save(tenant=tenant)
        enqueue(crawl_and_import_website_source, source.id)

    @extend_schema(
        tags=["Panel — baza wiedzy"],
        summary="Odśwież treść ze strony teraz",
        description=(
            "Ręczne pobranie treści, niezależne od częstotliwości z planu. "
            "Plan Start nie ma automatycznego odświeżania, więc to jedyny "
            "sposób, żeby bot dowiedział się o zmianach na stronie."
        ),
        request=None,
        responses={202: MessageSerializer},
    )
    @action(detail=True, methods=["post"])
    def recrawl(self, request, pk=None):
        source = self.get_object()
        enqueue(crawl_and_import_website_source, source.id)
        return Response(
            {"message": "Odświeżanie rozpoczęte. Potrwa chwilę."},
            status=status.HTTP_202_ACCEPTED,
        )
