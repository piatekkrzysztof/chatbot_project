"""
Rozmowa właściciela z własnym botem, z panelu.

Bez tego po wgraniu wiedzy nie ma jak sprawdzić, czy bot cokolwiek z niej
umie — jedyną drogą było wystawienie go na żywo na stronie i czekanie na
prawdziwego odwiedzającego. Dla agencji to różnica między „wgrałem,
sprawdziłem, działa" a „wgrałem i mam nadzieję".

Ta sama wiedza, ten sam prompt, to samo rozpoznawanie odmowy co u klientów —
korzystamy wprost z silnika czatu, żeby test nie mógł się rozjechać z tym,
co widzi odwiedzający. Różnią się dwie rzeczy, obie celowo:

  • rozmowa nie zjada limitu wiadomości z pakietu, za który klient płaci
    (testowanie własnego bota nie może kosztować),
  • rozmowa ma source="test" i wypada ze statystyk, historii i raportu luk
    (patrz chat/zapytania.py).
"""

from django.http import StreamingHttpResponse
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsTenantMember
from api.schemas import (
    CzatTestowyHistoriaSerializer,
    CzatTestowyZadanieSerializer,
)
from api.throttles import APIKeyRateThrottle
from api.utils.chat_engine import stream_chat_message
from chat.models import ChatMessage, Conversation
from chat.zapytania import ZRODLO_TESTOWE


def rozmowa_testowa(tenant, user):
    """
    Jedna rozmowa testowa na osobę, wznawiana przy kolejnych wizytach.

    Osobna dla każdego pracownika, bo dwie osoby testujące jednocześnie
    mieszałyby sobie historię — a historia wchodzi do promptu, więc bot
    odpowiadałby na cudze pytania.
    """
    rozmowa, _ = Conversation.objects.get_or_create(
        tenant=tenant,
        user_identifier=f"panel:{user.id}",
        source=ZRODLO_TESTOWE,
        defaults={"status": "active"},
    )
    return rozmowa


@extend_schema_view(
    post=extend_schema(
        tags=["Panel — czat"],
        summary="Zadaj pytanie własnemu botowi",
        description=(
            "Odpowiedź wraca strumieniem SSE, identycznym z publicznym czatem "
            "widgetu — stąd brak serializatora odpowiedzi. Zdarzenia: "
            "`delta` (fragment treści) oraz `done` (source, sources, message_id). "
            "Nie zużywa limitu wiadomości i nie wchodzi do statystyk."
        ),
        request=CzatTestowyZadanieSerializer,
        responses={200: OpenApiResponse(description="Strumień text/event-stream")},
    ),
    get=extend_schema(
        tags=["Panel — czat"],
        summary="Dotychczasowy przebieg rozmowy testowej",
        responses=CzatTestowyHistoriaSerializer,
    ),
    delete=extend_schema(
        tags=["Panel — czat"],
        summary="Wyczyść rozmowę testową",
        responses={200: OpenApiResponse(description="Rozmowa wyczyszczona")},
    ),
)
class CzatTestowyView(APIView):
    permission_classes = [IsTenantMember]
    throttle_classes = [APIKeyRateThrottle]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            raise PermissionDenied("Brak uprawnień.")

        wiadomosc = str(request.data.get("message", "")).strip()
        if not wiadomosc:
            # 400, nie 403: to błąd w treści żądania, nie brak uprawnień
            raise ValidationError({"message": "Wiadomość nie może być pusta."})

        rozmowa = rozmowa_testowa(tenant, request.user)

        # on_billable pominięte świadomie: to jedyne miejsce, w którym rozmowa
        # nie jest naliczana. Właściciel sprawdzający własnego bota nie może
        # płacić za tę wiedzę wiadomościami ze swojego pakietu.
        strumien = stream_chat_message(tenant, rozmowa, wiadomosc)

        odpowiedz = StreamingHttpResponse(strumien, content_type="text/event-stream")
        odpowiedz["Cache-Control"] = "no-cache"
        odpowiedz["X-Accel-Buffering"] = "no"
        return odpowiedz

    def get(self, request):
        """Dotychczasowy przebieg — żeby odświeżenie panelu nie gubiło rozmowy."""
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            raise PermissionDenied("Brak uprawnień.")

        rozmowa = rozmowa_testowa(tenant, request.user)
        wiadomosci = ChatMessage.objects.filter(conversation=rozmowa).order_by("timestamp", "id")
        return Response(
            {
                "messages": [
                    {"sender": w.sender, "text": w.message, "source": w.source} for w in wiadomosci
                ]
            }
        )

    def delete(self, request):
        """Czyści rozmowę — po uzupełnieniu wiedzy testuje się od nowa."""
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            raise PermissionDenied("Brak uprawnień.")

        ChatMessage.objects.filter(conversation=rozmowa_testowa(tenant, request.user)).delete()
        return Response({"ok": True})
