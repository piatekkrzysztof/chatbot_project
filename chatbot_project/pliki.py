"""Zlecenie usunięcia należy do tej samej transakcji co zmiana właściciela pliku."""

import logging
import uuid
from contextlib import contextmanager
from pathlib import PurePosixPath

from django.conf import settings
from django.db import connections, router, transaction

logger = logging.getLogger(__name__)


def nazwa_brandingu(instance, filename):
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    return f"widget_branding/{uuid.uuid4().hex}{suffix}"


@contextmanager
def zapis_z_plikami(instance, *, update_fields=None, using=None):
    pola = (
        {"file"}
        if instance._meta.label_lower == "documents.document"
        else {"widget_logo", "widget_avatar"}
    )
    if not instance.pk or (update_fields is not None and not pola.intersection(update_fields)):
        yield
        return
    using = using or router.db_for_write(type(instance), instance=instance)
    with transaction.atomic(using=using):
        type(instance).objects.using(using).select_for_update().filter(pk=instance.pk).exists()
        yield


def _obudz(pk, using):
    from documents.usuwanie_plikow import usun_zlecony_plik

    try:
        # Bez synchronicznego fallbacku. Trwały wpis odzyska okresowy obchód.
        usun_zlecony_plik.apply_async(args=[pk, using], retry=False)
    except Exception:
        logger.warning("Zlecenie usunięcia czeka na obchód: id=%s", pk)


def usun_plik_po_zatwierdzeniu(magazyn, nazwa, *, using="default", tenant_id=None):
    from documents.models import UsunieciePliku
    from documents.usuwanie_plikow import cel_magazynu, sprawdz_nazwe

    if not nazwa:
        return
    if not connections[using].in_atomic_block:
        raise RuntimeError("Zlecenie usunięcia wymaga transakcji zmiany właściciela pliku")
    sprawdz_nazwe(nazwa)
    if magazyn == "documents":
        aliases = ["private_documents"]
        if not nazwa.startswith("private-documents/") and settings.ALLOW_LEGACY_DOCUMENT_READS:
            aliases.append("default")
    elif magazyn == "default":
        aliases = ["default"]
    else:
        raise ValueError("Nieobsługiwany magazyn")
    for alias in aliases:
        job = UsunieciePliku.objects.using(using).create(
            magazyn=alias,
            cel=cel_magazynu(alias),
            nazwa=nazwa,
            firma_id=tenant_id,
        )
        transaction.on_commit(lambda pk=job.pk: _obudz(pk, using), using=using)
