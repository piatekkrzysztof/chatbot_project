"""Krótki protokół zapisu/usunięcia; żadnej blokady podczas pracy AI."""

from contextlib import contextmanager
from hashlib import sha256
from uuid import UUID

from django.db import IntegrityError, connections, transaction
from rest_framework.exceptions import APIException


class RozmowaUsunieta(APIException):
    status_code = 410
    default_detail = "Rozmowa została usunięta. Rozpocznij nową rozmowę."
    default_code = "conversation_deleted"


def skrot_sesji(tenant_id, session_id):
    return sha256(f"conversation:{tenant_id}:{UUID(str(session_id))}".encode()).hexdigest()


def _blokuj_sesje(tenant_id, session_id, using="default", *, czekaj=True):
    skrot = skrot_sesji(tenant_id, session_id)
    klucz = int.from_bytes(bytes.fromhex(skrot[:16]), "big", signed=True)
    with connections[using].cursor() as cursor:
        if czekaj:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [klucz])
        else:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [klucz])
            if not cursor.fetchone()[0]:
                return None
    return skrot


@contextmanager
def blokada_rozmowy(conversation_id, tenant_id=None, using="default"):
    from chat.models import Conversation

    with transaction.atomic(using=using):
        qs = Conversation.objects.using(using).select_for_update().filter(pk=conversation_id)
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        rozmowa = qs.first()
        if rozmowa is None:
            raise RozmowaUsunieta()
        yield rozmowa


def otworz_rozmowe(*, tenant, session_id, defaults):
    from chat.models import Conversation, UsunietaRozmowa

    with transaction.atomic():
        skrot = _blokuj_sesje(tenant.pk, session_id)
        if UsunietaRozmowa.objects.filter(tenant=tenant, skrot_sesji=skrot).exists():
            raise RozmowaUsunieta()
        try:
            with transaction.atomic():
                return Conversation.objects.get_or_create(
                    tenant=tenant, session_id=session_id, defaults=defaults
                )
        except IntegrityError as blad:
            # Globalnie unikalny UUID może już należeć do innej firmy.
            if Conversation.objects.filter(session_id=session_id).exclude(tenant=tenant).exists():
                raise RozmowaUsunieta() from blad
            raise


def usun_rozmowe(tenant, session_id):
    from chat.models import Conversation, UsunietaRozmowa

    with transaction.atomic():
        skrot = _blokuj_sesje(tenant.pk, session_id)
        rozmowa = (
            Conversation.objects.select_for_update()
            .filter(tenant=tenant, session_id=session_id)
            .first()
        )
        if rozmowa is None:
            return None
        UsunietaRozmowa.objects.get_or_create(tenant=tenant, skrot_sesji=skrot)
        _, szczegoly = rozmowa.delete()
        return {label.split(".")[-1]: count for label, count in szczegoly.items()}
