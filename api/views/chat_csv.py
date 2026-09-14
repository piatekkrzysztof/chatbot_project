import csv
import io

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployee
from api.schemas import ErrorSerializer, MessageSerializer
from api.utils.mixins import TenantQuerysetMixin
from chat.eksport_csv import strumien_csv
from chat.models import Conversation, PromptLog
from chat.zapytania import ZRODLO_IMPORTU, logi_do_eksportu
from documents.uploads import LimitedMultiPartParser

# Import czyta cały plik przed zapisem, żeby błąd w dowolnym wierszu odrzucał
# plik w całości. Limit bajtów pilnuje handler uploadu (CSV_IMPORT_MAX_UPLOAD_BYTES),
# ten - liczby zapisów w jednej transakcji.
MAKS_WIERSZY_IMPORTU = 5000
WYMAGANE_KOLUMNY = {"prompt", "response"}


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
        tenant = request.user.tenant
        # Eksport dotyczy ruchu klientów; próby właściciela to nie ich dane.
        # Historia wgrana z importu zostaje - eksport to kopia danych firmy.
        logs = logi_do_eksportu(tenant).order_by("-created_at")

        wiersze = (
            [
                # conversation_id, nie conversation.id: rozmowa bywa pusta
                # po retencji (SET_NULL), a wtedy eksport kończył się
                # błędem 500 dla całej firmy. Przy okazji bez zapytania
                # o rozmowę dla każdego wiersza.
                log.conversation_id or "",
                log.prompt,
                log.response,
                log.tokens,
                log.source,
                log.model,
                log.created_at.isoformat(),
            ]
            for log in logs.iterator(chunk_size=1000)
        )
        return strumien_csv(
            f"prompt_logs_{tenant.id}.csv",
            ["conversation_id", "prompt", "response", "tokens", "source", "model", "created_at"],
            wiersze,
        )


class BladImportu(Exception):
    pass


def _wczytaj_wiersze(plik):
    """Całość pliku albo BladImportu - nigdy część."""
    try:
        tekst = plik.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BladImportu("Plik CSV musi być zapisany w kodowaniu UTF-8.") from None

    czytnik = csv.DictReader(io.StringIO(tekst, newline=""))
    try:
        kolumny = set(czytnik.fieldnames or [])
        if not WYMAGANE_KOLUMNY <= kolumny:
            raise BladImportu("Plik CSV musi mieć w pierwszym wierszu kolumny prompt i response.")
        wiersze = []
        for wiersz in czytnik:
            if not wiersz.get("prompt") or not wiersz.get("response"):
                continue  # pomiń niekompletne wiersze
            if len(wiersze) >= MAKS_WIERSZY_IMPORTU:
                raise BladImportu(
                    f"Plik CSV może mieć najwyżej {MAKS_WIERSZY_IMPORTU} wierszy z treścią."
                )
            wiersze.append((wiersz["prompt"], wiersz["response"]))
    except csv.Error:
        raise BladImportu(f"Nieprawidłowy plik CSV w wierszu {czytnik.line_num}.") from None
    return wiersze


@extend_schema(
    tags=["Panel — czat"],
    summary="Wgraj historię rozmów z pliku CSV",
    description=(
        "Plik w UTF-8 z kolumnami `prompt` i `response`. Zapisuje wszystkie wiersze albo "
        "żaden. Zaimportowane wpisy nie wchodzą do statystyk ruchu klientów."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {"file": {"type": "string", "format": "binary"}},
        }
    },
    responses={201: MessageSerializer, 400: ErrorSerializer, 413: ErrorSerializer},
)
class ImportPromptLogsCSVView(APIView):
    # Ten sam parser co upload dokumentów: limit bajtów liczony w trakcie odbioru.
    parser_classes = [LimitedMultiPartParser]
    permission_classes = [IsOwnerOrEmployee]

    def post(self, request):
        tenant = request.user.tenant

        csv_file = request.FILES.get("file")
        if not csv_file:
            return Response({"error": "Brak pliku CSV."}, status=status.HTTP_400_BAD_REQUEST)

        # Wcześniej wiersze zapisywały się pojedynczo w trakcie czytania pliku.
        # Błąd kodowania albo składni w połowie kończył się błędem 500 z połową
        # pliku w bazie, a ponowienie dublowało zapisaną część.
        try:
            wiersze = _wczytaj_wiersze(csv_file)
        except BladImportu as blad:
            return Response({"error": str(blad)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # filter().first(), nie get_or_create: dwie rozmowy importu (np. po
            # dwóch równoległych importach) blokowały wcześniej każdy kolejny
            # import błędem MultipleObjectsReturned.
            rozmowa = (
                Conversation.objects.filter(tenant=tenant, user_identifier=ZRODLO_IMPORTU)
                .order_by("id")
                .first()
            ) or Conversation.objects.create(
                tenant=tenant, user_identifier=ZRODLO_IMPORTU, source=ZRODLO_IMPORTU
            )
            PromptLog.objects.bulk_create(
                [
                    PromptLog(
                        tenant=tenant,
                        conversation=rozmowa,
                        prompt=prompt,
                        response=odpowiedz,
                        tokens=0,
                        source=ZRODLO_IMPORTU,
                        model="manual",
                    )
                    for prompt, odpowiedz in wiersze
                ]
            )

        return Response({"imported": len(wiersze)}, status=status.HTTP_201_CREATED)
