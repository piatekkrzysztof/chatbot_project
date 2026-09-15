from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsTenantMember
from api.schemas import ChatFeedbackRequestSerializer, ErrorSerializer, StatusSerializer
from api.serializers import ChatFeedbackSerializer
from api.throttles import APIKeyRateThrottle, SubscriptionRateThrottle
from chat.zapytania import ZRODLO_TESTOWE

# Ten sam komunikat co przy nieistniejącej wiadomości: odmowa nie może
# zdradzać, że wiadomość o tym numerze istnieje, tylko w innej rozmowie.
NIE_ZNALEZIONO = "Nie znaleziono wiadomości od bota."


def zapisz_ocene(request, tenant, dozwolona):
    """
    Wspólna obsługa oceny dla panelu i widgetu.

    `dozwolona(wiadomosc)` decyduje, czy ten, kto ocenia, ma prawo ocenić tę
    wiadomość. Firma jest już sprawdzona w serializerze.
    """
    serializer = ChatFeedbackSerializer(data=request.data, context={"tenant": tenant})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    if not dozwolona(serializer.context["message"]):
        return Response({"message_id": [NIE_ZNALEZIONO]}, status=status.HTTP_400_BAD_REQUEST)
    serializer.save()
    return Response({"status": "success"})


@extend_schema(
    tags=["Panel — czat"],
    summary="Oceń odpowiedź bota w rozmowie testowej (panel)",
    description=(
        "Wyłącznie rozmowy z czatu testowego w panelu. Oceny prawdziwych rozmów "
        "wystawia odwiedzający w widgecie."
    ),
    request=ChatFeedbackRequestSerializer,
    responses={200: StatusSerializer, 400: ErrorSerializer},
)
class SubmitFeedbackView(APIView):
    """
    Ocena z panelu - tylko dla rozmów testowych.

    Wiadomość ma jedną ocenę. Wcześniej członek zespołu (także w roli
    `viewer`) mógł z panelu nadpisać ocenę wystawioną przez odwiedzającego,
    a filtr „pomocne/niepomocne" w logach i każda liczba z ocen mówią
    o zadowoleniu klientów, nie zespołu.
    """

    permission_classes = [IsTenantMember]

    def post(self, request):
        return zapisz_ocene(
            request,
            request.user.tenant,
            lambda wiadomosc: wiadomosc.conversation.source == ZRODLO_TESTOWE,
        )


@extend_schema(
    tags=["Widget"],
    summary="Oceń odpowiedź bota",
    description=(
        "Kciuk w górę lub w dół przy konkretnej odpowiedzi. Identyfikator "
        "wiadomości przychodzi w odpowiedzi czatu — w polu `message_id`, "
        "a przy strumieniu w zdarzeniu `done`. `conversation_session_id` musi być "
        "tym samym identyfikatorem sesji, z którym wysłano pytanie."
    ),
    request=ChatFeedbackRequestSerializer,
    responses={200: StatusSerializer, 400: ErrorSerializer},
)
class PublicFeedbackView(APIView):
    """
    Ocena wystawiana przez odwiedzającego stronę klienta.

    Panelowy odpowiednik wymaga tokenu JWT, więc widget nie miał jak go wywołać —
    endpoint istniał, a kciuków w oknie czatu nie było. Tutaj tożsamość firmy
    ustala klucz API, a serializer sprawdza, że oceniana wiadomość należy
    właśnie do niej.

    Klucz API widgetu jest publiczny - stoi w kodzie strony klienta. Samo
    sprawdzenie firmy pozwalało więc każdemu ocenić dowolną odpowiedź tej firmy,
    podając kolejne numery wiadomości, i ustawić jej oceny według uznania.
    Ocena wymaga teraz identyfikatora sesji rozmowy, do której należy
    wiadomość - zna go tylko przeglądarka, która tę rozmowę prowadziła.
    """

    authentication_classes = []
    permission_classes = []
    # Ruch odwiedzających - limit czatu firmy, nie limit panelu
    throttle_classes = [APIKeyRateThrottle, SubscriptionRateThrottle]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            raise PermissionDenied("Nieprawidłowy klucz API")
        sesja = str(request.data.get("conversation_session_id") or "")
        return zapisz_ocene(
            request,
            tenant,
            lambda wiadomosc: bool(sesja) and str(wiadomosc.conversation.session_id) == sesja,
        )
