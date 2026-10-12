import logging

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.mfa_reset import wylacz_drugi_skladnik, wyslij_ostrzezenie
from accounts.models import CustomUser, DrugiSkladnik, Tenant, UserRole
from accounts.seats import sprawdz_limit_miejsc
from api.mfa_throttles import MfaThrottle, account_attempt
from api.permissions import IsOwner, IsOwnerOrEmployee
from api.serializers import UserSerializer
from api.utils.mixins import TenantQuerysetMixin
from api.views.account_security import confirm_factor

logger = logging.getLogger(__name__)


class ResetMfaSerializer(serializers.Serializer):
    """Hasło właściciela i - gdy sam ma MFA - jego kod albo kod zapasowy."""

    haslo = serializers.CharField(max_length=1024, trim_whitespace=False, write_only=True)
    kod = serializers.CharField(max_length=64, required=False, allow_blank=True)


class ResetMfaWynikSerializer(serializers.Serializer):
    zakonczonych_sesji = serializers.IntegerField()
    ostrzezenie_wyslane = serializers.BooleanField()


@extend_schema(tags=["Panel — zespół"])
class UserViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsOwner]
    queryset = CustomUser.objects.all()

    def get_queryset(self):
        # Jedno podzapytanie zamiast pytania o MFA dla każdej osoby z listy.
        return (
            super()
            .get_queryset()
            .annotate(
                mfa_wlaczone=Exists(
                    DrugiSkladnik.objects.filter(
                        uzytkownik=OuterRef("pk"), potwierdzony_od__isnull=False
                    )
                )
            )
        )

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsOwnerOrEmployee()]
        return super().get_permissions()

    def _lock_team(self):
        # Jedna blokada firmy porządkuje równoległe zmiany różnych właścicieli.
        # Blokowanie tylko edytowanego konta nie chroniłoby ostatniego ownera.
        tenant = Tenant.objects.select_for_update().get(pk=self.request.user.tenant_id)
        try:
            self.request.user.refresh_from_db(fields=["role", "is_active"])
        except CustomUser.DoesNotExist:
            # Inny właściciel mógł usunąć autora, kiedy żądanie czekało na blokadę.
            self.request.user.pk = None
            raise PermissionDenied("Konto nie ma już dostępu do zespołu.") from None
        if not self.request.user.is_active or self.request.user.role != UserRole.OWNER:
            raise PermissionDenied("Tylko właściciel może zarządzać zespołem.")
        return tenant

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        tenant = self._lock_team()
        sprawdz_limit_miejsc(tenant)
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        self._lock_team()
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        self._lock_team()
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)

    @extend_schema(
        summary="Zresetuj logowanie dwuetapowe osoby z zespołu",
        description=(
            "Dla osoby, która straciła telefon i kody zapasowe. Właściciel potwierdza "
            "własnym hasłem i - gdy sam ma MFA - kodem. Usuwa składnik i kody osoby, "
            "kończy jej sesje i wysyła jej mail ostrzegawczy. Wpis w dzienniku firmy."
        ),
        request=ResetMfaSerializer,
        responses={200: ResetMfaWynikSerializer},
    )
    @action(detail=True, methods=["post"], url_path="reset-mfa", throttle_classes=[MfaThrottle])
    def reset_mfa(self, request, pk=None):
        """
        Decyzja właściciela z 11.10.2026 (docs/utrata-mfa.md, krok 1).

        Bez tego jedyną drogą dla osoby z zespołu było usunięcie i ponowne
        zaproszenie - nowe konto, a historia działań pod starym. Hasło i kod
        właściciela, bo przejęta sesja właściciela nie może wystarczyć do zdjęcia
        ochrony z cudzego konta.
        """
        with transaction.atomic():
            # Najpierw dostęp, potem treść żądania: osoba z innej firmy ma dać
            # 404, a nie „brak hasła” - kontrakt dostępu wymaga, żeby odmowa
            # zapadała przed walidacją (test_kontrakt_dostepu).
            self._lock_team()
            osoba = self.get_object()
            dane = ResetMfaSerializer(data=request.data)
            dane.is_valid(raise_exception=True)
            if osoba.pk == request.user.pk:
                raise ValidationError(
                    {"detail": "Swoje logowanie dwuetapowe wyłączysz w Ustawieniach konta."}
                )
            autor = CustomUser.objects.select_for_update().get(pk=request.user.pk)
            account_attempt(autor)
            if not autor.check_password(dane.validated_data["haslo"]):
                raise ValidationError({"detail": "Nieprawidłowe hasło."})
            confirm_factor(autor, dane.validated_data)
            osoba = CustomUser.objects.select_for_update().get(pk=osoba.pk)
            if not DrugiSkladnik.objects.filter(uzytkownik=osoba).exists():
                raise ValidationError(
                    {"detail": "Ta osoba nie ma włączonego logowania dwuetapowego."}
                )
            teraz = timezone.now()
            zakonczone = wylacz_drugi_skladnik(osoba, teraz)

        # Po zatwierdzeniu: mail nie może cofnąć resetu, ale właściciel musi
        # wiedzieć, że ostrzeżenie nie poszło, i powiedzieć osobie inaczej.
        try:
            wyslij_ostrzezenie(osoba, teraz, f"właściciel firmy ({autor.email})")
            wyslane = True
        except Exception:
            logger.exception("Nie wyslano ostrzezenia o resecie MFA: user=%s", osoba.pk)
            wyslane = False
        return Response({"zakonczonych_sesji": zakonczone, "ostrzezenie_wyslane": wyslane})

    def _require_another_owner(self, instance):
        if instance.role != UserRole.OWNER or not instance.is_active:
            return
        if (
            not CustomUser.objects.filter(
                tenant_id=instance.tenant_id, role=UserRole.OWNER, is_active=True
            )
            .exclude(pk=instance.pk)
            .exists()
        ):
            raise ValidationError("Firma musi mieć co najmniej jednego aktywnego właściciela.")

    def perform_update(self, serializer):
        role = serializer.validated_data.get("role", serializer.instance.role)
        active = serializer.validated_data.get("is_active", serializer.instance.is_active)
        if role != UserRole.OWNER or not active:
            self._require_another_owner(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_another_owner(instance)
        if instance.pk == self.request.user.pk:
            # delete() wyzeruje pk także w kontekście autora żądania. Dziennik
            # zachowa nazwę, ale nie utworzy FK do właśnie usuniętego konta.
            instance = self.request.user
        instance.delete()
