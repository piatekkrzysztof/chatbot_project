"""Trwałe, ponawialne usuwanie obiektów; żadnych kluczy dostępu w bazie i alarmach."""

import hashlib
import json
import logging
import time
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath

from botocore.config import Config
from botocore.exceptions import ClientError
from celery import shared_task
from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from storages.backends.s3 import S3Storage

from chatbot_project.storage import UnconfiguredPrivateStorage
from documents.models import Document, UsunieciePliku

logger = logging.getLogger(__name__)
MAX_PROB = 8
ZAKONCZONE = ("gotowe", "zachowany")
DZIERZAWA = timedelta(minutes=10)


class BlokadaUsuniecia(Exception):
    pass


def sprawdz_nazwe(nazwa):
    path = PurePosixPath(nazwa)
    if (
        not nazwa
        or len(nazwa) > 512
        or path.is_absolute()
        or str(path) != nazwa
        or any(p in (".", "..") for p in path.parts)
        or any(c in nazwa for c in "\\:\x00")
        or any(ord(c) < 32 for c in nazwa)
    ):
        raise BlokadaUsuniecia("nieprawidlowa_nazwa")


def cel_magazynu(alias):
    if alias not in ("default", "private_documents"):
        raise BlokadaUsuniecia("nieznany_magazyn")
    storage = storages[alias]
    if isinstance(storage, FileSystemStorage):
        identity = ["filesystem", str(Path(storage.location).resolve())]
    elif isinstance(storage, S3Storage):
        identity = [
            "s3",
            storage.endpoint_url,
            storage.region_name,
            storage.bucket_name,
            storage.location,
        ]
    elif isinstance(storage, UnconfiguredPrivateStorage):
        identity = ["unconfigured", alias]
    else:
        raise BlokadaUsuniecia("nieobslugiwany_backend")
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _magazyn_do_usuwania(alias):
    storage = storages[alias]
    if isinstance(storage, UnconfiguredPrivateStorage):
        raise BlokadaUsuniecia("magazyn_nieskonfigurowany")
    if isinstance(storage, S3Storage):
        # Oddzielny klient: nie zmieniamy timeoutów uploadu ani współdzielonego klienta.
        config = dict(storages.backends[alias])
        config["OPTIONS"] = dict(config.get("OPTIONS", {}))
        config["OPTIONS"]["client_config"] = Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 1, "mode": "standard"},
            signature_version=storage.signature_version,
        )
        return storages.create_storage(config)
    return storage


def _uzywany(job, using):
    from accounts.models import Tenant

    # Konserwatywnie: także stare nazwy dokumentów, które mogły leżeć w obu magazynach.
    if Document.objects.using(using).filter(file=job.nazwa).exists():
        return True
    return (
        job.magazyn == "default"
        and Tenant.objects.using(using)
        .filter(Q(widget_logo=job.nazwa) | Q(widget_avatar=job.nazwa))
        .exists()
    )


def _kod_bledu(error):
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code")
        return {
            "AccessDenied": "brak_uprawnien",
            "InvalidAccessKeyId": "brak_uprawnien",
            "SignatureDoesNotMatch": "brak_uprawnien",
            "NoSuchBucket": "brak_bucketa",
        }.get(code, "blad_magazynu")
    return "blad_magazynu"


def _gotowe(now):
    return Q(stan="oczekuje", ponow_at__lte=now) | Q(stan="praca", dzierzawa_do__lte=now)


def wykonaj_usuniecie(pk, using="default"):
    now = timezone.now()
    jobs = UsunieciePliku.objects.using(using)
    with transaction.atomic(using=using):
        job = jobs.select_for_update(skip_locked=True).filter(pk=pk).filter(_gotowe(now)).first()
        if job is None:
            return False
        if job.proby >= MAX_PROB:
            job.stan, job.blad = "blad", "wyczerpane_proby"
            job.save(update_fields=["stan", "blad"], using=using)
            return False
        job.stan, job.token = "praca", uuid.uuid4()
        job.proby += 1
        job.dzierzawa_do = now + DZIERZAWA
        job.save(update_fields=["stan", "token", "proby", "dzierzawa_do"], using=using)
    # Stan próby zatwierdzony. Nie trzymamy transakcji ani blokady wiersza przez HTTP.
    current = jobs.filter(pk=pk, token=job.token, stan="praca")
    try:
        sprawdz_nazwe(job.nazwa)
        if cel_magazynu(job.magazyn) != job.cel:
            raise BlokadaUsuniecia("zmieniony_magazyn")
        if _uzywany(job, using):
            raise BlokadaUsuniecia("plik_nadal_uzywany")
        storage = _magazyn_do_usuwania(job.magazyn)
        try:
            storage.delete(job.nazwa)
        except FileNotFoundError:
            pass  # Ponowienie po skasowaniu bajtów, ale przed potwierdzeniem w bazie.
    except BlokadaUsuniecia as error:
        if str(error) == "plik_nadal_uzywany":
            # Wspólny plik logo/awatara pozostaje legalnie używany. Jego ostatni
            # właściciel utworzy nowe zlecenie; nie alarmujemy o prawidłowym stanie.
            current.update(
                stan="zachowany", blad=str(error), dzierzawa_do=None, zakonczono_at=timezone.now()
            )
        else:
            current.update(stan="blad", blad=str(error), dzierzawa_do=None)
            logger.error("Usunięcie zablokowane: id=%s kod=%s", pk, str(error))
    except Exception as error:
        current.update(
            stan="blad" if job.proby >= MAX_PROB else "oczekuje",
            blad=_kod_bledu(error),
            dzierzawa_do=None,
            ponow_at=timezone.now() + timedelta(seconds=min(60 * 2 ** (job.proby - 1), 3600)),
        )
        # Wyjątki SDK mogą zawierać adresy i nagłówki. Do logu trafia tylko ID.
        logger.warning("Nie udało się usunąć pliku: id=%s; zlecenie zachowane", pk)
    else:
        current.update(stan="gotowe", zakonczono_at=timezone.now(), blad="", dzierzawa_do=None)
    return True


def zalegle(now=None):
    now = now or timezone.now()
    return UsunieciePliku.objects.exclude(stan__in=ZAKONCZONE).filter(
        Q(stan="blad") | Q(utworzono_at__lte=now - timedelta(minutes=15))
    )


def alarmuj():
    from accounts.czuwanie import adresy_operatora

    now = timezone.now()
    rows = list(
        zalegle(now)
        .filter(Q(alarm_at__isnull=True) | Q(alarm_at__lt=now - timedelta(hours=1)))
        .order_by("utworzono_at", "pk")[:50]
    )
    rows = [
        row
        for row in rows
        if UsunieciePliku.objects.filter(pk=row.pk, token=row.token, alarm_at=row.alarm_at)
        .exclude(stan__in=ZAKONCZONE)
        .update(alarm_at=now)
    ]
    if not rows:
        return 0
    body = (
        "Usuwanie plików wymaga kontroli operatora. Uruchom kontrola_usuwania_plikow.\n"
        + "\n".join(
            f"Zlecenie {j.pk}: {j.stan}, próby={j.proby}, kod={j.blad or 'zalegle'}." for j in rows
        )
    )
    try:
        if not send_mail(
            "Pliki: zaległe usunięcia",
            body,
            settings.DEFAULT_FROM_EMAIL,
            adresy_operatora(),
            fail_silently=False,
        ):
            raise RuntimeError("Brak potwierdzenia wysyłki")
    except Exception:
        for row in rows:
            UsunieciePliku.objects.filter(pk=row.pk, token=row.token, alarm_at=now).update(
                alarm_at=row.alarm_at
            )
        logger.error("Nie wysłano alarmu zaległych usunięć plików")
        return 0
    for row in rows:
        UsunieciePliku.objects.filter(pk=row.pk, token=row.token).exclude(
            stan__in=ZAKONCZONE
        ).update(alarm_at=now)
    return len(rows)


def ponow_usuniecie(pk):
    with transaction.atomic():
        job = UsunieciePliku.objects.select_for_update().get(pk=pk)
        if job.stan in ZAKONCZONE or (job.stan == "praca" and job.dzierzawa_do > timezone.now()):
            raise BlokadaUsuniecia("zlecenie_gotowe_lub_w_trakcie")
        sprawdz_nazwe(job.nazwa)
        if cel_magazynu(job.magazyn) != job.cel:
            raise BlokadaUsuniecia("zmieniony_magazyn")
        if _uzywany(job, "default"):
            raise BlokadaUsuniecia("plik_nadal_uzywany")
        job.stan, job.blad, job.proby = "oczekuje", "", 0
        job.ponow_at, job.token = timezone.now(), uuid.uuid4()
        job.alarm_at, job.dzierzawa_do = None, None
        job.save()


@shared_task(ignore_result=True, soft_time_limit=50, time_limit=60)
def usun_zlecony_plik(pk, using="default"):
    return wykonaj_usuniecie(pk, using)


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=120)
def usun_oczekujace_pliki():
    poczatek = time.monotonic()
    ids = list(
        UsunieciePliku.objects.filter(_gotowe(timezone.now()))
        .order_by("ponow_at", "pk")
        .values_list("pk", flat=True)[:50]
    )
    for pk in ids:
        if time.monotonic() - poczatek >= 60:
            break
        wykonaj_usuniecie(pk)
    # Tylko zakończone ślady; nie gubimy niewykonanych zleceń ani wyczerpanych prób.
    stare = list(
        UsunieciePliku.objects.filter(
            stan__in=ZAKONCZONE, zakonczono_at__lt=timezone.now() - timedelta(days=30)
        ).values_list("pk", flat=True)[:200]
    )
    UsunieciePliku.objects.filter(pk__in=stare, stan__in=ZAKONCZONE).delete()
    return alarmuj()
