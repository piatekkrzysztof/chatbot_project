"""
Podgląd tego, jak serwer rozpoznaje adres odwiedzającego.

TRUSTED_PROXY_DEPTH trzeba ustawić na liczbę serwerów pośredniczących, a tej
nie da się wiarygodnie odgadnąć z dokumentacji hostingu — zależy od tego, czy
ruch idzie przez CDN, load balancer, czy oba. Zła wartość jest kosztowna w obie
strony: za mała skleja wszystkich odwiedzających w jedną tożsamość i limit
zablokuje widget wszystkim naraz, za duża pozwala podrobić adres nagłówkiem
i obejść limit.

Dlatego zamiast zgadywać, właściciel może zobaczyć wprost, co serwer widzi.
"""
from drf_spectacular.utils import OpenApiResponse, extend_schema
from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsOwnerOrEmployee, IsOwnerOrEmployeeOrTenantReadOnly
from chat.privacy import anonymize_ip, client_ip


@extend_schema(
    tags=["Panel — diagnostyka"],
    summary="Jak serwer widzi adres odwiedzającego",
    description=(
        "Zwraca surowe dane o pochodzeniu żądania i wyliczony z nich adres "
        "klienta. Służy do sprawdzenia, czy TRUSTED_PROXY_DEPTH jest ustawione "
        "poprawnie dla danego hostingu."
    ),
    responses={200: OpenApiResponse(description="Rozpoznanie adresu.")},
)
class DiagnostykaAdresuView(APIView):
    """Tylko dla zalogowanego właściciela — pokazuje pochodzenie żądania."""
    permission_classes = [IsOwnerOrEmployeeOrTenantReadOnly]

    def get(self, request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        lancuch = [wpis.strip() for wpis in forwarded.split(",") if wpis.strip()]
        depth = getattr(settings, "TRUSTED_PROXY_DEPTH", 0)
        rozpoznany = client_ip(request)

        return Response({
            "trusted_proxy_depth": depth,
            "remote_addr": request.META.get("REMOTE_ADDR"),
            "x_forwarded_for": lancuch,
            "rozpoznany_adres": rozpoznany,
            # To trafia do bazy jako identyfikator rozmówcy
            "zapisywany_identyfikator": anonymize_ip(rozpoznany),
            "podpowiedz": self.podpowiedz(depth, lancuch),
        })

    @staticmethod
    def podpowiedz(depth, lancuch):
        if not lancuch:
            return (
                "Brak nagłówka X-Forwarded-For — albo żądanie poszło wprost "
                "do aplikacji, albo hosting go nie ustawia. Przy braku proxy "
                "poprawną wartością jest 0."
            )
        if depth == 0:
            return (
                f"Nagłówek ma {len(lancuch)} wpisów, a TRUSTED_PROXY_DEPTH wynosi 0 — "
                f"wszyscy odwiedzający są więc widziani jako jeden adres. "
                f"Prawdopodobnie właściwa wartość to {len(lancuch)}."
            )
        if depth > len(lancuch):
            return (
                f"TRUSTED_PROXY_DEPTH ({depth}) jest większe niż liczba wpisów "
                f"w nagłówku ({len(lancuch)}). Bierzemy wtedy najstarszy wpis, "
                f"który pochodzi od klienta i da się go podrobić."
            )
        return (
            "Wartość wygląda spójnie z nagłówkiem. Sprawdź, czy rozpoznany "
            "adres zgadza się z Twoim publicznym IP."
        )
