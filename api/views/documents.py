import logging

from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from api.schemas import DocumentUploadSerializer, ErrorSerializer, MessageSerializer
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from pypdf.errors import PyPdfError

from documents.utils.pdf_parser import extract_text_from_pdf
from documents.validators import sprawdz_limit_bazy_wiedzy
from api.serializers import DocumentSerializer

# Ta sama zasada odczytu wartości logicznej co w ustawieniach widgetu:
# formularz multipart przysyła "true"/"false" jako tekst.
from api.views.widget import _wlaczone
from documents.models import Document, DocumentChunk, WebsiteSource
from documents.utils.embedding_generator import generate_embeddings_for_document
from documents.tasks import embed_document_task, crawl_and_import_website_source
from documents.utils.queue import enqueue
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.exceptions import ValidationError
from api.serializers import DocumentChunkSerializer, WebsiteSourceSerializer
from api.utils.mixins import TenantQuerysetMixin
from api.permissions import *

logger = logging.getLogger(__name__)


class DocumentDetailView(TenantQuerysetMixin, RetrieveAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().order_by("-uploaded_at")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = DocumentSerializer(instance).data
        data["chunk_count"] = instance.chunks.count()
        data["status"] = (
            "ready"
            if instance.processed and instance.chunks.exists()
            else ("processing" if not instance.processed else "processed_no_chunks")
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
    responses={201: DocumentSerializer, 400: ErrorSerializer},
)
class UploadDocumentView(APIView):
    parser_classes = [MultiPartParser]
    permission_classes = [IsOwnerOrEmployee]

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
            try:
                text = extract_text_from_pdf(file)
            except PyPdfError as blad:
                # Uszkodzony PDF to nie przypadek brzegowy: urwane pobieranie,
                # plik ze skanera, dokument zapisany przez program, ktory sie
                # wysypal. Uzytkownik nie ma jak tego rozpoznac przed wgraniem.
                #
                # Bez tej obslugi wychodzila piecsetka - dla wgrywajacego
                # nieodroznialna od awarii serwisu, a w Sentry szum zamiast
                # sygnalu. pypdf 6 zglasza tu takze LimitReachedError, czyli
                # przerwana probe przetworzenia pliku zbudowanego tak, zeby
                # zajac caly czas procesora; to rowniez ma byc odmowa, nie awaria.
                logger.info("Nie udalo sie odczytac PDF-a %s: %s", file.name, blad)
                return Response(
                    {
                        "error": "Nie udało się odczytać tego pliku PDF. Sprawdź, czy nie jest uszkodzony."
                    },
                    status=400,
                )

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
