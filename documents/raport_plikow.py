"""Odczyt metadanych plików; kandydat bez odwołania nie jest zgodą na kasowanie."""

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from botocore.config import Config
from django.core.files.storage import FileSystemStorage, storages
from django.db.models import Q
from django.utils import timezone
from storages.backends.s3 import S3Storage

from accounts.models import Tenant
from documents.models import Document, UsunieciePliku
from documents.usuwanie_plikow import ZAKONCZONE, cel_magazynu

PREFIKSY = {
    "default": ("widget_branding/", "documents/"),
    "private_documents": ("private-documents/", "documents/"),
}
STANY = (
    "powiazany",
    "zlecenie_usuniecia",
    "zlecenie_inny_cel",
    "zlecenie_zakonczone",
    "swiezy",
    "do_weryfikacji",
    "niepewne_metadane",
    "pominiety_specjalny",
)


class NiepelnyRaport(Exception):
    pass


@dataclass(frozen=True)
class Obiekt:
    nazwa: str
    bajty: int | None
    zmieniono: datetime | None
    specjalny: bool = False


class Budzet:
    def __init__(self, sekundy, limit):
        self.koniec = time.monotonic() + sekundy
        self.wpisy = 0
        self.limit_wpisow = limit * 4 + 1000

    def sprawdz(self):
        if time.monotonic() >= self.koniec:
            raise NiepelnyRaport("limit_czasu")

    def wpis(self):
        self.sprawdz()
        self.wpisy += 1
        if self.wpisy > self.limit_wpisow:
            raise NiepelnyRaport("limit_wpisow_katalogow")


def _lokalne(storage, prefiks, budzet):
    root = Path(storage.location)
    if not root.is_dir():
        raise NiepelnyRaport("brak_katalogu_magazynu")
    start = root / prefiks

    def walk(directory, depth):
        budzet.sprawdz()
        if depth > 32:
            raise NiepelnyRaport("limit_glebokosci")
        with os.scandir(directory) as entries:
            for entry in entries:
                budzet.wpis()
                name = Path(entry.path).relative_to(root).as_posix()
                if entry.is_symlink():
                    yield Obiekt(name, None, None, specjalny=True)
                elif entry.is_dir(follow_symlinks=False):
                    yield from walk(entry.path, depth + 1)
                elif entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    yield Obiekt(name, stat.st_size, datetime.fromtimestamp(stat.st_mtime, UTC))
                else:
                    yield Obiekt(name, None, None, specjalny=True)

    if start.is_symlink():
        yield Obiekt(prefiks.rstrip("/"), None, None, specjalny=True)
    elif start.exists():
        yield from walk(start, 0)


def _s3(storage, alias, prefiks, budzet):
    config = dict(storages.backends[alias])
    config["OPTIONS"] = dict(config.get("OPTIONS", {}))
    config["OPTIONS"]["client_config"] = Config(
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 1, "mode": "standard"},
        signature_version=storage.signature_version,
    )
    client = storages.create_storage(config).connection.meta.client
    location = storage.location.strip("/")
    base = f"{location}/" if location else ""
    token = None
    while True:
        budzet.sprawdz()
        request = {"Bucket": storage.bucket_name, "Prefix": base + prefiks, "MaxKeys": 250}
        if token:
            request["ContinuationToken"] = token
        page = client.list_objects_v2(**request)
        for item in page.get("Contents", []):
            budzet.wpis()
            key = item["Key"]
            if not key.startswith(base + prefiks):
                raise NiepelnyRaport("niezgodny_prefiks")
            yield Obiekt(
                key[len(base) :],
                item.get("Size"),
                item.get("LastModified"),
                specjalny=key.endswith("/"),
            )
        if not page.get("IsTruncated"):
            return
        following = page.get("NextContinuationToken")
        if not following or following == token:
            raise NiepelnyRaport("nieprawidlowa_paginacja")
        token = following


def obiekty(alias, budzet):
    storage = storages[alias]
    for prefix in PREFIKSY[alias]:
        budzet.sprawdz()
        if isinstance(storage, FileSystemStorage):
            yield from _lokalne(storage, prefix, budzet)
        elif isinstance(storage, S3Storage):
            yield from _s3(storage, alias, prefix, budzet)
        else:
            raise NiepelnyRaport("nieobslugiwany_magazyn")


def _klasyfikuj(partia, alias, cel, granica):
    names = [obj.nazwa for obj in partia]
    # Konserwatywnie zachowujemy także dokumenty o historycznych nazwach,
    # które mogły znajdować się w obydwu magazynach.
    refs = set(Document.objects.filter(file__in=names).values_list("file", flat=True).distinct())
    if alias == "default":
        for field in ("widget_logo", "widget_avatar"):
            refs.update(
                Tenant.objects.filter(**{f"{field}__in": names})
                .values_list(field, flat=True)
                .distinct()
            )
    jobs = {}
    for name, target, status in (
        UsunieciePliku.objects.filter(Q(magazyn=alias) | Q(cel=cel), nazwa__in=names)
        .values_list("nazwa", "cel", "stan")
        .distinct()
        .iterator(chunk_size=250)
    ):
        jobs.setdefault(name, set()).add(
            "zlecenie_inny_cel"
            if target != cel
            else "zlecenie_zakonczone"
            if status in ZAKONCZONE
            else "zlecenie_usuniecia"
        )
    for obj in partia:
        pending = jobs.get(obj.nazwa, set())
        if obj.specjalny:
            state = "pominiety_specjalny"
        elif obj.nazwa in refs:
            state = "powiazany"
        elif "zlecenie_usuniecia" in pending:
            state = "zlecenie_usuniecia"
        elif "zlecenie_inny_cel" in pending:
            state = "zlecenie_inny_cel"
        elif "zlecenie_zakonczone" in pending:
            state = "zlecenie_zakonczone"
        elif (
            not isinstance(obj.zmieniono, datetime)
            or timezone.is_naive(obj.zmieniono)
            or type(obj.bajty) is not int
            or obj.bajty < 0
        ):
            state = "niepewne_metadane"
        elif obj.zmieniono > granica:
            state = "swiezy"
        else:
            state = "do_weryfikacji"
        yield obj, state


def raport(alias, *, limit=10000, sekundy=60, wiek=24, probka=100, nazwy=False):
    if (
        alias not in PREFIKSY
        or not 1 <= limit <= 100000
        or not 1 <= sekundy <= 300
        or not 1 <= wiek <= 8760
        or not 0 <= probka <= 1000
    ):
        raise ValueError("Nieprawidlowe granice raportu")
    start = timezone.now()
    budget = Budzet(sekundy, limit)
    counts = {state: {"obiekty": 0, "bajty": 0} for state in STANY}
    sample = []
    seen = 0
    code = ""
    target = ""
    batch = []

    def classify():
        nonlocal seen
        for obj, state in _klasyfikuj(batch, alias, target, start - timedelta(hours=wiek)):
            seen += 1
            counts[state]["obiekty"] += 1
            if type(obj.bajty) is int and obj.bajty >= 0:
                counts[state]["bajty"] += obj.bajty
            if state != "powiazany" and len(sample) < probka:
                row = {
                    "id": hashlib.sha256((alias + ":" + obj.nazwa).encode()).hexdigest(),
                    "stan": state,
                    "bajty": obj.bajty,
                    "zmieniono": (
                        obj.zmieniono.isoformat() if isinstance(obj.zmieniono, datetime) else None
                    ),
                }
                if nazwy:
                    row["nazwa"] = obj.nazwa
                sample.append(row)
        batch.clear()

    try:
        target = cel_magazynu(alias)
        for obj in obiekty(alias, budget):
            budget.sprawdz()
            if seen + len(batch) >= limit:
                classify()
                raise NiepelnyRaport("limit_obiektow")
            batch.append(obj)
            if len(batch) == 250:
                classify()
        classify()
    except NiepelnyRaport as error:
        code = str(error)
    except Exception:
        # Odpowiedź SDK/wyjątek ścieżki może zawierać nazwy i dane dostępowe.
        code = "blad_odczytu"
    return {
        "format": 1,
        "magazyn": alias,
        "cel": target,
        "prefiksy": list(PREFIKSY[alias]),
        "rozpoczeto": start.isoformat(),
        "zakonczono": timezone.now().isoformat(),
        "pelny_zakres_prefiksow": not code,
        "kod": code,
        "minimalny_wiek_godzin": wiek,
        "sprawdzone_obiekty": seen,
        "niesklasyfikowane_w_partii": len(batch),
        "stany": counts,
        "probka": sample,
        "probka_ograniczona": sum(v["obiekty"] for k, v in counts.items() if k != "powiazany")
        > len(sample),
        "uwaga": "Odczyt na żywo, bez wspólnej migawki bazy i magazynu. Nie uprawnia do kasowania.",
    }
