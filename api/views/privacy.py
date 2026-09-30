from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployee, IsOwnerOrEmployeeOrTenantReadOnly
from api.schemas import ErasureResultSerializer, ErrorSerializer, PrivacySettingsSerializer
from chat.lifecycle import usun_rozmowe


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
        serializer = PrivacySettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changed = list(serializer.validated_data)
        for field, value in serializer.validated_data.items():
            setattr(tenant, field, value)

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

    Wspólna blokada z zapisującymi i CASCADE obejmują logi oraz kontakty.
    Minimalny znacznik blokuje odtworzenie skasowanej sesji przez stare żądanie.
    """

    permission_classes = [IsOwnerOrEmployee]

    def delete(self, request, session_id):
        tenant = request.user.tenant

        removed = usun_rozmowe(tenant, session_id)
        if removed is None:
            raise NotFound("Nie znaleziono rozmowy o tym identyfikatorze.")

        return Response({"deleted": removed})
