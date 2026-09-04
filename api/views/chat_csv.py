import csv
from io import TextIOWrapper

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployee
from api.schemas import ErrorSerializer, MessageSerializer
from api.utils.mixins import TenantQuerysetMixin
from chat.models import Conversation, PromptLog, Tenant
from chat.zapytania import logi_klientow


@extend_schema(
    tags=["Panel — czat"],
    summary="Pobierz historię rozmów jako CSV",
    responses={(200, "text/csv"): OpenApiResponse(description="Plik CSV z logami rozmów.")},
)
class ExportPromptLogsCSVView(TenantQuerysetMixin, ListAPIView):
    serializer_class = None
    # Bylo IsTenantMember, czyli takze `viewer`. Te same dane widac wprawdzie
    # przez /api/chat/logs/, ale stronicowany odczyt w panelu a wyciagniecie
    # calej historii rozmow jednym zadaniem to inny profil ryzyka. Rola
    # `viewer` jest z zalozenia do ogladania, nie do wynoszenia.
    permission_classes = [IsOwnerOrEmployee]
    queryset = PromptLog.objects.all()

    def get(self, request, *args, **kwargs):
        logs = self.get_queryset().order_by("-created_at")
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("Brak klucza API.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Niepoprawny klucz API.") from None

        # Eksport dotyczy ruchu klientów; próby właściciela to nie ich dane.
        logs = logi_klientow(tenant).order_by("-created_at")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="prompt_logs_{tenant.id}.csv"'

        writer = csv.writer(response)
        writer.writerow(
            ["conversation_id", "prompt", "response", "tokens", "source", "model", "created_at"]
        )

        for log in logs:
            writer.writerow(
                [
                    log.conversation.id,
                    log.prompt,
                    log.response,
                    log.tokens,
                    log.source,
                    log.model,
                    log.created_at.isoformat(),
                ]
            )

        return response


@extend_schema(
    tags=["Panel — czat"],
    summary="Wgraj historię rozmów z pliku CSV",
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {"file": {"type": "string", "format": "binary"}},
        }
    },
    responses={201: MessageSerializer, 400: ErrorSerializer},
)
class ImportPromptLogsCSVView(APIView):
    parser_classes = [MultiPartParser]
    permission_classes = [IsOwnerOrEmployee]

    def post(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied("Brak klucza API.")

        try:
            tenant = Tenant.objects.get(api_key=api_key)
        except Tenant.DoesNotExist:
            raise PermissionDenied("Niepoprawny klucz API.") from None

        csv_file = request.FILES.get("file")
        if not csv_file:
            return Response({"error": "Brak pliku CSV."}, status=status.HTTP_400_BAD_REQUEST)

        decoded = TextIOWrapper(csv_file.file, encoding="utf-8")
        reader = csv.DictReader(decoded)

        created = 0
        for row in reader:
            if not row.get("prompt") or not row.get("response"):
                continue  # pomiń niekompletne wiersze

            conv, _ = Conversation.objects.get_or_create(tenant=tenant, user_identifier="imported")

            PromptLog.objects.create(
                tenant=tenant,
                conversation=conv,
                prompt=row["prompt"],
                response=row["response"],
                tokens=0,
                source="imported",
                model="manual",
            )
            created += 1

        return Response({"imported": created}, status=status.HTTP_201_CREATED)
