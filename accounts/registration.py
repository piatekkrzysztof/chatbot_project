"""Shared validation for public account creation and team email changes."""

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
