"""
Włączanie, potwierdzanie i wyłączanie drugiego składnika.

Konfiguracja jest dwuetapowa celowo: sekret powstaje przy rozpoczęciu, ale
drugi składnik zaczyna obowiązywać dopiero po przepisaniu poprawnego kodu.
Bez tego rozdziału ktoś, kto zeskanuje kod QR i zamknie kartę, zostałby
z włączoną ochroną i bez działającej aplikacji - czyli zamknięty na zewnątrz
własnego konta.
"""

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import dwuskladnikowe, totp
from accounts.models import CustomUser, DrugiSkladnik, KodZapasowy
from api.mfa_throttles import MfaThrottle, account_attempt


class KodSerializer(serializers.Serializer):
    """Sam kod z aplikacji albo kod zapasowy."""

    kod = serializers.CharField(max_length=64)


class HasloSerializer(serializers.Serializer):
    haslo = serializers.CharField(max_length=1024, trim_whitespace=False, write_only=True)


class HasloIKodSerializer(HasloSerializer):
    """
    Wyłączenie ochrony wymaga obu rzeczy naraz.

    Porwana sesja daje dostęp do panelu, ale nie do hasła ani do telefonu -
    więc żadne z nich osobno nie może wystarczyć.
    """

    kod = serializers.CharField(max_length=64)


class StanSerializer(serializers.Serializer):
    wlaczony = serializers.BooleanField()
    w_trakcie_konfiguracji = serializers.BooleanField()
    kodow_zapasowych = serializers.IntegerField()


class RozpoczecieSerializer(serializers.Serializer):
    sekret = serializers.CharField()
    adres_otpauth = serializers.CharField()


class PotwierdzenieSerializer(serializers.Serializer):
    wlaczony = serializers.BooleanField()
    kody_zapasowe = serializers.ListField(child=serializers.CharField())


class MFAMutationView(APIView):
    throttle_classes = [MfaThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


@extend_schema(
    tags=["Konto — drugi składnik"],
    summary="Stan drugiego składnika",
    request=None,
    responses={200: StanSerializer},
)
class StanDrugiegoSkladnikaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, zadanie):
        skladnik = DrugiSkladnik.objects.filter(uzytkownik=zadanie.user).first()
        return Response(
            {
                "wlaczony": bool(skladnik and skladnik.wlaczony),
                "w_trakcie_konfiguracji": bool(skladnik and not skladnik.wlaczony),
                "kodow_zapasowych": KodZapasowy.objects.filter(
                    uzytkownik=zadanie.user, uzyty__isnull=True
                ).count(),
            }
        )


@extend_schema(
    tags=["Konto — drugi składnik"],
    summary="Rozpocznij konfigurację",
    description="Wymaga aktualnego hasła. Zwraca sekret i adres otpauth do kodu QR.",
    request=HasloSerializer,
    responses={201: RozpoczecieSerializer},
)
class RozpocznijDrugiSkladnikView(MFAMutationView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, zadanie):
        serializer = HasloSerializer(data=zadanie.data)
        serializer.is_valid(raise_exception=True)
        zadanie.user = CustomUser.objects.select_for_update().get(pk=zadanie.user.pk)
        account_attempt(zadanie.user)
        if not zadanie.user.check_password(serializer.validated_data["haslo"]):
            return Response({"error": "Nieprawidłowe hasło."}, status=400)
        skladnik = DrugiSkladnik.objects.filter(uzytkownik=zadanie.user).first()

        if skladnik and skladnik.wlaczony:
            # Nadpisanie sekretu działającego drugiego składnika unieważniłoby
            # aplikację, której użytkownik właśnie używa - i zrobiłoby to
            # jednym żądaniem, bez potwierdzenia hasłem.
            return Response(
                {"error": "Drugi składnik jest już włączony. Najpierw go wyłącz."},
                status=status.HTTP_409_CONFLICT,
            )

        sekret = totp.nowy_sekret()
        if skladnik:
            # Powtórzone rozpoczęcie zaczyna od nowa: poprzedni, niepotwierdzony
            # sekret mógł trafić do aplikacji na innym telefonie.
            skladnik.sekret = sekret
            skladnik.ostatni_krok = None
            skladnik.save(update_fields=["sekret", "ostatni_krok"])
        else:
            skladnik = DrugiSkladnik.objects.create(uzytkownik=zadanie.user, sekret=sekret)

        return Response(
            {
                "sekret": skladnik.sekret,
                "adres_otpauth": totp.adres_do_aplikacji(
                    skladnik.sekret,
                    zadanie.user.username,
                    dwuskladnikowe.nazwa_wydawcy(),
                ),
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Konto — drugi składnik"],
    summary="Potwierdź konfigurację kodem",
    description="Włącza drugi składnik i wydaje kody zapasowe. Kody pokazujemy jeden raz.",
    request=HasloIKodSerializer,
    responses={200: PotwierdzenieSerializer},
)
class PotwierdzDrugiSkladnikView(MFAMutationView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, zadanie):
        serializer = HasloIKodSerializer(data=zadanie.data)
        serializer.is_valid(raise_exception=True)
        zadanie.user = CustomUser.objects.select_for_update().get(pk=zadanie.user.pk)
        account_attempt(zadanie.user)
        if not zadanie.user.check_password(serializer.validated_data["haslo"]):
            return Response({"error": "Nieprawidłowe hasło."}, status=400)
        skladnik = DrugiSkladnik.objects.filter(uzytkownik=zadanie.user).first()
        if not skladnik:
            return Response(
                {"error": "Najpierw rozpocznij konfigurację."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if skladnik.wlaczony:
            return Response(
                {"error": "Drugi składnik jest już włączony."},
                status=status.HTTP_409_CONFLICT,
            )

        if not dwuskladnikowe.sprawdz_kod(skladnik, serializer.validated_data["kod"]):
            return Response(
                {"error": "Kod nie pasuje. Sprawdź, czy zegar telefonu jest ustawiony poprawnie."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        skladnik.potwierdzony_od = timezone.now()
        skladnik.save(update_fields=["potwierdzony_od"])

        return Response(
            {
                "wlaczony": True,
                # Jedyny raz, kiedy te kody istnieją poza głową użytkownika.
                # W bazie są wyłącznie skróty, więc pokazanie ich ponownie
                # jest niemożliwe - i tak ma być.
                "kody_zapasowe": dwuskladnikowe.wygeneruj_kody_zapasowe(zadanie.user),
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Konto — drugi składnik"],
    summary="Wyłącz drugi składnik",
    description="Wymaga hasła oraz aktualnego kodu albo kodu zapasowego.",
    request=HasloIKodSerializer,
    responses={200: StanSerializer},
)
class WylaczDrugiSkladnikView(MFAMutationView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, zadanie):
        serializer = HasloIKodSerializer(data=zadanie.data)
        serializer.is_valid(raise_exception=True)
        zadanie.user = CustomUser.objects.select_for_update().get(pk=zadanie.user.pk)
        account_attempt(zadanie.user)
        skladnik = DrugiSkladnik.objects.filter(uzytkownik=zadanie.user).first()
        if not skladnik or not skladnik.wlaczony:
            return Response(
                {"error": "Drugi składnik nie jest włączony."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Hasło ORAZ kod, nie jedno z dwojga. Wyłączenie ochrony jest operacją
        # tej samej wagi co logowanie, więc porwana sesja nie może wystarczyć:
        # ktoś, kto przejął zalogowaną kartę, ma sesję, ale nie ma ani hasła,
        # ani telefonu.
        if not zadanie.user.check_password(serializer.validated_data["haslo"]):
            return Response({"error": "Nieprawidłowe hasło."}, status=status.HTTP_400_BAD_REQUEST)

        kod = serializer.validated_data["kod"]
        if not (
            dwuskladnikowe.sprawdz_kod(skladnik, kod)
            or dwuskladnikowe.zuzyj_kod_zapasowy(zadanie.user, kod)
        ):
            return Response({"error": "Kod nie pasuje."}, status=status.HTTP_400_BAD_REQUEST)

        KodZapasowy.objects.filter(uzytkownik=zadanie.user).delete()
        skladnik.delete()

        return Response({"wlaczony": False}, status=status.HTTP_200_OK)
