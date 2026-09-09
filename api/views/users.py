from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import CustomUser, Tenant, UserRole
from accounts.seats import sprawdz_limit_miejsc
from api.permissions import IsOwner, IsOwnerOrEmployee
from api.serializers import UserSerializer
from api.utils.mixins import TenantQuerysetMixin


@extend_schema(tags=["Panel — zespół"])
class UserViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsOwner]
    queryset = CustomUser.objects.all()

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
