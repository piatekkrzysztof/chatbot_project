"""
Usuwanie danych rozmów po okresie przechowywania ustalonym przez klienta.

RODO nie pozwala trzymać danych osobowych bezterminowo "na wszelki wypadek".
Rozmowy zawierają treść pytań odwiedzających, skrócony adres IP i zostawione
kontakty, więc muszą znikać same — poleganie na tym, że ktoś pamięta o ręcznym
czyszczeniu, nie jest polityką retencji.
"""

import logging

from django.utils import timezone
from datetime import timedelta

from accounts.models import Tenant
from chat.models import ChatUsageLog, ContactRequest, Conversation, PromptLog

logger = logging.getLogger(__name__)


def purge_tenant(tenant, now=None):
    """
    Kasuje dane rozmów jednego klienta starsze niż jego okres retencji.

    Zwraca słownik z liczbą usuniętych obiektów w rozbiciu na modele — dzięki temu
    da się to zaraportować i sprawdzić, że polityka faktycznie działa.
    """
    retention_days = tenant.data_retention_days or 0
    if retention_days <= 0:
        return {}

    cutoff = (now or timezone.now()) - timedelta(days=retention_days)
    removed = {}

    # PromptLog i ChatUsageLog wskazują konwersację przez SET_NULL, więc nie znikną
    # razem z nią — trzeba je usunąć osobno, inaczej treść pytań zostaje w bazie
    # mimo skasowanej rozmowy.
    for model, field in (
        (PromptLog, "created_at"),
        (ChatUsageLog, "created_at"),
        (ContactRequest, "created_at"),
        (Conversation, "last_message_at"),
    ):
        # delete() zwraca sumę razem z kaskadami, więc licznik rozmów obejmowałby
        # też skasowane wiadomości — do raportu bierzemy rozbicie na modele.
        _, per_model = model.objects.filter(tenant=tenant, **{f"{field}__lt": cutoff}).delete()
        for label, count in per_model.items():
            name = label.split(".")[-1]
            removed[name] = removed.get(name, 0) + count

    if removed:
        logger.info(
            "Retencja %s: usunięto dane starsze niż %s dni (%s)",
            tenant.name,
            retention_days,
            removed,
        )

    return removed


def purge_all_tenants(now=None):
    """Przebiega wszystkich klientów; jeden błąd nie może zatrzymać reszty."""
    total = {}

    for tenant in Tenant.objects.all():
        try:
            removed = purge_tenant(tenant, now=now)
        except Exception:
            logger.exception("Retencja nie powiodła się dla %s", tenant.name)
            continue

        for name, count in removed.items():
            total[name] = total.get(name, 0) + count

    return total
