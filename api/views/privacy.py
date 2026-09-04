from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployee, IsOwnerOrEmployeeOrTenantReadOnly
from api.schemas import ErasureResultSerializer, ErrorSerializer, PrivacySettingsSerializer
from chat.models import ChatUsageLog, ContactRequest, Conversation, PromptLog


@extend_schema(
    tags=["Panel — RODO"],
    summary="Okres przechowywania danych i polityka prywatności",
    request=PrivacySettingsSerializer,
    responses={200: PrivacySettingsSerializer, 400: ErrorSerializer},
)
class TenantPrivacySettingsView(APIView):
    """
    Ustawienia RODO należące do klienta: jak długo trzymamy rozmowy i dokąd
    prowadzi jego polityka prywatności pokazywana w widgecie.

    To administrator danych decyduje o okresie przechowywania, nie dostawca
    narzędzia — dlatego jest to ustawienie w panelu, a nie stała w kodzie.
    """

    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]

    def _serialize(self, tenant):
        return {
            "data_retention_days": tenant.data_retention_days,
            "privacy_policy_url": tenant.privacy_policy_url or "",
        }

    def get(self, request):
        return Response(self._serialize(request.user.tenant))

    def patch(self, request):
        tenant = request.user.tenant
        changed = []

        if "data_retention_days" in request.data:
            try:
                days = int(request.data["data_retention_days"])
            except (TypeError, ValueError):
                return Response(
                    {"data_retention_days": "Podaj liczbę dni (0 wyłącza usuwanie)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if days < 0:
                return Response(
                    {"data_retention_days": "Liczba dni nie może być ujemna."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            tenant.data_retention_days = days
            changed.append("data_retention_days")

        if "privacy_policy_url" in request.data:
            tenant.privacy_policy_url = request.data["privacy_policy_url"] or ""
            changed.append("privacy_policy_url")

        if changed:
            tenant.save(update_fields=changed)

        return Response(self._serialize(tenant))


@extend_schema(
    tags=["Panel — RODO"],
    summary="Usuń wszystkie dane jednej rozmowy",
    description=(
        "Realizacja prawa do bycia zapomnianym. Kasuje rozmowę, jej wiadomości "
        "oraz logi i zapytania kontaktowe z nią powiązane. Nieodwracalne."
    ),
    responses={200: ErasureResultSerializer, 404: ErrorSerializer},
)
class ConversationEraseView(APIView):
    """
    Usunięcie wszystkich danych jednej rozmowy — realizacja prawa do bycia
    zapomnianym, gdy odwiedzający o to poprosi.

    Kasuje też logi wskazujące konwersację przez SET_NULL: bez tego treść pytań
    zostawałaby w PromptLog mimo "usuniętej" rozmowy, więc żądanie usunięcia
    byłoby spełnione tylko pozornie.
    """

    permission_classes = [IsOwnerOrEmployee]

    def delete(self, request, session_id):
        tenant = request.user.tenant

        conversation = Conversation.objects.filter(tenant=tenant, session_id=session_id).first()
        if conversation is None:
            raise NotFound("Nie znaleziono rozmowy o tym identyfikatorze.")

        removed = {}

        def record(per_model):
            # delete() sumuje też kaskady, więc do raportu bierzemy rozbicie na modele
            for label, count in per_model.items():
                name = label.split(".")[-1]
                removed[name] = removed.get(name, 0) + count

        for model in (PromptLog, ChatUsageLog, ContactRequest):
            _, per_model = model.objects.filter(tenant=tenant, conversation=conversation).delete()
            record(per_model)

        _, per_model = conversation.delete()
        record(per_model)

        return Response({"deleted": removed})
