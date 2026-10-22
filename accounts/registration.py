"""Shared validation for public account creation and team email changes."""

import unicodedata

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower, Trim
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import CustomUser, Tenant, UserRole


def lock_invitation_team(user):
    try:
        tenant = Tenant.objects.select_for_update().get(pk=user.tenant_id)
    except Tenant.DoesNotExist:
        raise PermissionDenied("Firma nie jest już dostępna.") from None
    if not CustomUser.objects.filter(
        pk=user.pk, tenant=tenant, is_active=True, role=UserRole.OWNER
    ).exists():
        raise PermissionDenied("Tylko aktywny właściciel może zarządzać zaproszeniami.")
    return tenant


#: Komunikat przy nazwie firmy ze znakiem sterującym.
NAZWA_ZE_ZNAKIEM_STERUJACYM = "Nazwa firmy nie może zawierać znaków nowej linii ani tabulacji."


def ma_znaki_sterujace(tekst):
    """
    Czy w tekście jest znak sterujący (nowa linia, tabulacja, NUL i reszta Cc).

    Nazwa firmy trafia do tematu każdego maila do właściciela, a Django odrzuca
    temat ze znakiem nowej linii. Do 2.32.12 taka nazwa po cichu wyłączała
    wszystkie powiadomienia firmy (audyt 2026-10, P15).
    """
    return any(unicodedata.category(znak) == "Cc" for znak in tekst)


def normalized_email(value):
    return value.strip().lower()


def unique_email(value, instance=None):
    value = normalized_email(value)
    if not value:
        return value
    users = CustomUser.objects.annotate(canonical_email=Lower(Trim("email"))).filter(
        canonical_email=value
    )
    if instance is not None:
        users = users.exclude(pk=instance.pk)
    if users.exists():
        raise ValidationError("Konto z tym adresem e-mail już istnieje.")
    return value


def check_password(password, **attributes):
    try:
        validate_password(password, CustomUser(**attributes))
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages}) from None


def account_conflict(exc):
    """Convert only uniqueness violations; other storage errors remain visible."""
    cause = exc.__cause__
    if (
        getattr(cause, "sqlstate", None) == "23505"
        or getattr(cause, "pgcode", None) == "23505"
        or "UNIQUE constraint failed" in str(exc)
    ):
        raise ValidationError(
            {"email": "Adres e-mail lub nazwa użytkownika są już zajęte."}
        ) from None
    raise exc


def create_user(**attributes):
    try:
        with transaction.atomic():
            return CustomUser.objects.create_user(**attributes)
    except IntegrityError as exc:
        account_conflict(exc)
