"""
Ustawienia firmy dostępne z panelu.

Powstało z konkretnego braku: strona Zapytania przy nieudanym powiadomieniu
radzi „uzupełnij adres e-mail w ustawieniach konta", a takich ustawień
w panelu nie było. Jedyną drogą był Django admin, do którego klient nie ma
i nie powinien mieć dostępu — komunikat wysyłał go więc donikąd.

Celowo bardzo wąskie. To nie są ustawienia widgetu (te są osobno) ani konta
użytkownika — to dane samej firmy, których zmiana zmienia zachowanie systemu
wobec świata: dokąd trafiają powiadomienia i pod jaką nazwą przedstawia się
bot w mailach.
"""

from django.core.exceptions import ValidationError as BladWalidacji
from django.core.validators import validate_email
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwner
from api.schemas import UstawieniaFirmySerializer


def _stan(tenant):
    return {
        "name": tenant.name,
        "owner_email": tenant.owner_email or "",
    }


@extend_schema_view(
    get=extend_schema(
        tags=["Panel — konto"],
        summary="Ustawienia firmy",
        responses=UstawieniaFirmySerializer,
    ),
    patch=extend_schema(
        tags=["Panel — konto"],
        summary="Zmień ustawienia firmy",
        request=UstawieniaFirmySerializer,
        responses=UstawieniaFirmySerializer,
    ),
)
class UstawieniaFirmyView(APIView):
    # Tylko właściciel: adres powiadomień decyduje o tym, kto dowiaduje się
    # o zapytaniach od klientów. Pracownik nie powinien móc przekierować
    # tego strumienia na siebie ani go po cichu wyłączyć.
    permission_classes = [IsOwner]

    def get(self, request):
        return Response(_stan(self._firma(request)))

    def patch(self, request):
        tenant = self._firma(request)
        zmienione = []

        if "name" in request.data:
            nazwa = str(request.data["name"]).strip()
            if not nazwa:
                raise ValidationError({"name": "Nazwa firmy nie może być pusta."})
            tenant.name = nazwa[:100]
            zmienione.append("name")

        if "owner_email" in request.data:
            adres = str(request.data["owner_email"]).strip()
            if adres:
                try:
                    validate_email(adres)
                except BladWalidacji:
                    raise ValidationError({"owner_email": "To nie jest poprawny adres e-mail."})
            # Pusty adres jest dozwolony i znaczy „nie powiadamiaj" — panel
            # mówi o tym wprost. Odrzucanie pustej wartości zamykałoby jedyną
            # drogę wypisania się z powiadomień.
            tenant.owner_email = adres
            zmienione.append("owner_email")

        if zmienione:
            tenant.save(update_fields=zmienione)

        return Response(_stan(tenant))

    def _firma(self, request):
        tenant = getattr(request.user, "tenant", None)
        if tenant is None:
            raise PermissionDenied("Konto nie jest powiązane z firmą.")
        return tenant
