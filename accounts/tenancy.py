"""Sprawdzenie już ustalonej firmy żądania; nagłówek nigdy jej nie wybiera."""

from uuid import UUID

from rest_framework.exceptions import PermissionDenied


def verified_request_tenant(request):
    tenant = getattr(request, "tenant", None)
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        if (
            not user.is_active
            or not user.tenant_id
            or tenant is None
            or user.tenant_id != tenant.pk
        ):
            raise PermissionDenied("Brak dostępu do tej firmy.")

    # Starsi klienci panelu mogą nadal wysyłać klucz swojej firmy obok JWT.
    # Dopuszczamy zgodny klucz, ale nie traktujemy go jako uprawnienia do innej firmy.
    key = getattr(request, "headers", {}).get("X-API-Key")
    if tenant is not None and key:
        try:
            matches = UUID(str(key)) == tenant.api_key
        except (ValueError, TypeError, AttributeError):
            matches = False
        if not matches:
            raise PermissionDenied("Klucz API nie pasuje do firmy tego żądania.")

    return tenant
