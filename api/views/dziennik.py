"""
Odczyt dziennika audytowego przez właściciela firmy.

Bez tego widoku dziennik byłby tabelą, do której zagląda wyłącznie dostawca -
czyli dokładnie tym, czego klient nie może pokazać własnemu audytorowi.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination

from accounts.models import WpisDziennika
from api.permissions import IsOwner
from api.utils.mixins import TenantQuerysetMixin


class StronicowanieDziennika(PageNumberPagination):
    """
    Rozmiar strony podany WPROST.

    `PageNumberPagination` bez `page_size` nie stronicuje niczego - DRF zwraca
    wtedy całą listę i nie sygnalizuje tego w żaden sposób. Przy dzienniku,
    który rośnie z każdą zmianą w panelu i nigdy się nie kurczy, oznaczałoby
    to prędzej czy później jedną odpowiedź z dziesiątkami tysięcy wpisów.
    """

    page_size = 50
    page_size_query_param = "rozmiar"
    max_page_size = 200


class WpisDziennikaSerializer(serializers.ModelSerializer):
    class Meta:
        model = WpisDziennika
        fields = ["id", "czas", "nazwa_uzytkownika", "metoda", "sciezka", "status", "adres_ip"]


@extend_schema(
    tags=["Panel — bezpieczeństwo"],
    summary="Dziennik audytowy firmy",
    description=(
        "Kto, co, kiedy i skąd. Wyłącznie żądania zmieniające dane - odczyty "
        "nie są zapisywane. Treści żądań nie są przechowywane."
    ),
)
class DziennikView(TenantQuerysetMixin, ListAPIView):
    """
    Tylko do odczytu i tylko dla właściciela.

    Dziennik bez możliwości edycji jest jedyną wersją, która cokolwiek znaczy:
    zapis, który da się poprawić po fakcie, nie jest dowodem niczego. Stąd brak
    końcówek zapisujących i kasujących - również dla nas.

    Rola `employee` celowo nie ma tu dostępu. Dziennik pokazuje działania
    wszystkich osób w firmie, więc jego odczyt jest uprawnieniem nadzorczym,
    a nie roboczym.
    """

    queryset = WpisDziennika.objects.all()
    serializer_class = WpisDziennikaSerializer
    pagination_class = StronicowanieDziennika
    permission_classes = [IsOwner]

    def get_queryset(self):
        return super().get_queryset().order_by("-czas")
