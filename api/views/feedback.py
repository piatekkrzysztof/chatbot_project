from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsTenantMember
from api.schemas import ChatFeedbackRequestSerializer, ErrorSerializer, StatusSerializer
from api.serializers import ChatFeedbackSerializer


def zapisz_ocene(request, tenant):
    """Wspólna obsługa oceny dla panelu i widgetu — różni je tylko sposób uwierzytelnienia."""
    serializer = ChatFeedbackSerializer(data=request.data, context={"tenant": tenant})
    if serializer.is_valid():
        serializer.save()
        return Response({"status": "success"})
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["Panel — czat"],
    summary="Oceń odpowiedź bota (panel)",
    request=ChatFeedbackRequestSerializer,
    responses={200: StatusSerializer, 400: ErrorSerializer},
)
class SubmitFeedbackView(APIView):
    permission_classes = [IsTenantMember]

    def post(self, request):
        return zapisz_ocene(request, request.user.tenant)


@extend_schema(
    tags=["Widget"],
    summary="Oceń odpowiedź bota",
    description=(
        "Kciuk w górę lub w dół przy konkretnej odpowiedzi. Identyfikator "
        "wiadomości przychodzi w odpowiedzi czatu — w polu `message_id`, "
        "a przy strumieniu w zdarzeniu `done`."
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
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            raise PermissionDenied("Nieprawidłowy klucz API")
        return zapisz_ocene(request, tenant)
