"""
Odczyt i zmiana danych do faktury.

Bez tego widoku dane zebrane przy rejestracji byłyby nie do poprawienia:
firma zmienia adres, wchodzi w spółkę, dostaje NIP - a klient musiałby pisać
do nas z prośbą o edycję własnych danych.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response

from accounts import nip as nip_pl
from accounts.models import DaneRozliczeniowe
from api.permissions import IsOwner


class DaneRozliczenioweSerializer(serializers.ModelSerializer):
    class Meta:
        model = DaneRozliczeniowe
        fields = ["nazwa", "nip", "ulica", "kod_pocztowy", "miasto", "kraj"]

    def validate_nip(self, value):
        """
        Ta sama reguła co przy rejestracji.

        Gdyby edycja sprawdzała mniej niż rejestracja, wystarczyłoby wejść
        w ustawienia, żeby wpisać NIP z literówką - czyli reguła obowiązywałaby
        wyłącznie przy pierwszym wpisaniu, a to najmniej ważny moment.
        """
        if not value:
            return ""
        if not nip_pl.poprawny(value):
            raise serializers.ValidationError(
                "Ten NIP ma nieprawidłową sumę kontrolną. Sprawdź, czy cyfry się nie przestawiły."
            )
        return nip_pl.znormalizuj(value)

    def validate_kraj(self, value):
        return (value or "PL").upper()


@extend_schema(
    tags=["Panel — rozliczenia"],
    summary="Dane do faktury",
    description="Odczyt i zmiana danych, na które wystawiamy faktury.",
)
class DaneRozliczenioweView(RetrieveUpdateAPIView):
    """
    Tylko dla właściciela.

    Dane rozliczeniowe decydują o tym, na kogo idzie faktura i z kim jest
    zawarta umowa - to nie jest ustawienie robocze. Pracownik zmieniający
    adres firmy na fakturze byłby przy okazji najprostszą drogą do wystawienia
    dokumentu na kogoś innego.
    """

    serializer_class = DaneRozliczenioweSerializer
    permission_classes = [IsOwner]

    def get_object(self):
        # Konta założone przed wprowadzeniem tych pól nie mają jeszcze wiersza.
        # Tworzymy go pusty zamiast zwracać 404: klient ma zobaczyć formularz
        # do wypełnienia, a nie komunikat o braku zasobu.
        dane, _ = DaneRozliczeniowe.objects.get_or_create(
            tenant=self.request.tenant,
            defaults={
                "nazwa": self.request.tenant.name,
                "ulica": "",
                "kod_pocztowy": "",
                "miasto": "",
            },
        )
        return dane

    def update(self, request, *args, **kwargs):
        # Częściowa aktualizacja także przy PUT: panel wysyła komplet, ale
        # klient API nie ma powodu przepisywać pól, których nie zmienia.
        kwargs["partial"] = True
        return super().update(request, *args, **kwargs)
