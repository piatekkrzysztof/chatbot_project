from rest_framework.exceptions import PermissionDenied

from accounts.tenancy import verified_request_tenant


class TenantQuerysetMixin:
    """
    Mixin ograniczający queryset tylko do obiektów należących do request.tenant.
    Wymaga istnienia pola 'tenant' w modelu.
    """

    def get_queryset(self):
        tenant = verified_request_tenant(self.request)
        if tenant is None:
            raise PermissionDenied("Brak dostępu do tej firmy.")
        base_queryset = super().get_queryset()
        return base_queryset.filter(tenant=tenant)
