class TenantQuerysetMixin:
    """
    Mixin ograniczający queryset tylko do obiektów należących do request.tenant.
    Wymaga istnienia pola 'tenant' w modelu.
    """
    def get_queryset(self):
        base_queryset = super().get_queryset()
        return base_queryset.filter(tenant=self.request.tenant)