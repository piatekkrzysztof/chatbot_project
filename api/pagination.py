"""
Stronicowanie list panelu (F16).

`PageNumberPagination` bez `page_size` nie stronicuje niczego - DRF zwraca wtedy
całą listę i nie sygnalizuje tego w żaden sposób. Tak było z historią rozmów:
widok miał klasę stronicowania, a ekran Konwersacje i tak dostawał wszystkie
wpisy od początku działania firmy przy każdym wejściu.
"""

from rest_framework.pagination import PageNumberPagination


class StronicowaniePanelu(PageNumberPagination):
    """Rozmiar strony podany WPROST, z twardym górnym limitem."""

    page_size = 50
    page_size_query_param = "rozmiar"
    max_page_size = 200
