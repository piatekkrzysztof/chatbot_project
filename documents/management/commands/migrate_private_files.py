"""Powtarzalna migracja: kopiuj, porównaj, opcjonalnie usuń zweryfikowane źródło."""

import hashlib
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from accounts.backups import backup_cipher, decrypt_backup, encrypt_backup, read_backup
from chatbot_project.storage import UnconfiguredPrivateStorage
from documents.models import Document


def digest(storage, name):
    result = hashlib.sha256()
    with storage.open(name, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.digest()


def backup_names(storage, directory="backups"):
    try:
        directories, files = storage.listdir(directory)
    except FileNotFoundError:
        return
    for name in files:
        if name.lower().endswith(".json"):
            yield f"{directory}/{name}"
    for name in directories:
        yield from backup_names(storage, f"{directory}/{name}")


class Command(BaseCommand):
    help = "Domyślnie tylko inwentaryzuje. --apply kopiuje; --delete-source usuwa po weryfikacji."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=["documents", "backups", "all"], default="all")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--delete-source", action="store_true")

    def handle(self, *args, **options):
        if options["delete_source"] and not options["apply"]:
            raise CommandError("--delete-source wymaga --apply.")
        source = storages["default"]
        count = 0
        for kind in ("documents", "backups"):
            if options["kind"] not in (kind, "all"):
                continue
            target = storages[f"private_{kind}"]
            if options["apply"]:
                if isinstance(target, UnconfiguredPrivateStorage) or target is source:
                    raise CommandError("Skonfiguruj oddzielny prywatny magazyn przed migracją.")
                if kind == "backups":
                    backup_cipher()
            if kind == "documents":
                names = (
                    Document.objects.exclude(file__isnull=True)
                    .exclude(file="")
                    .values_list("file", flat=True)
                    .distinct()
                    .iterator(chunk_size=200)
                )
            else:
                names = backup_names(source)
            for name in names:
                if name.startswith("private-documents/"):
                    continue
                if not name.startswith(f"{kind}/") or ".." in PurePosixPath(name).parts:
                    raise CommandError("Niespodziewany klucz pliku; wymaga ręcznej weryfikacji.")
                count += 1
                if not options["apply"]:
                    continue
                if kind == "documents":
                    self.copy_document(source, target, name, options["delete_source"])
                else:
                    self.copy_backup(source, target, name, options["delete_source"])
        mode = "Zweryfikowano" if options["apply"] else "Do sprawdzenia (bez zmian)"
        self.stdout.write(f"{mode}: {count} plików.")
        if options["apply"] and not options["delete_source"]:
            self.stdout.write(
                "Stare pliki nadal istnieją; po kontroli dostępu powtórz z --delete-source."
            )

    def copy_document(self, source, target, name, delete_source):
        if not source.exists(name):
            if target.exists(name):
                return  # Wcześniejszy przebieg już przeniósł plik.
            raise CommandError("Brakuje dokumentu w obu magazynach; migracja przerwana.")
        expected = digest(source, name)
        if not target.exists(name):
            with source.open(name, "rb") as stream:
                saved = target.save(name, stream)
            if saved != name:
                target.delete(saved)
                raise CommandError("Równoległy zapis zmienił nazwę celu; ponów migrację.")
            try:
                if digest(target, name) != expected:
                    raise CommandError("Niezgodna suma dokumentu; źródło pozostaje bez zmian.")
            except Exception:
                target.delete(name)  # Wyłącznie nowa, niezweryfikowana kopia.
                raise
        if digest(target, name) != expected:
            raise CommandError("Prywatny plik ma inną zawartość; nie nadpisuję żadnej kopii.")
        if delete_source:
            if digest(source, name) != expected:
                raise CommandError("Źródło zmieniło się podczas migracji; nie usuwam go.")
            source.delete(name)

    def copy_backup(self, source, target, name, delete_source):
        with source.open(name, "rb") as stream:
            plaintext = read_backup(stream)
        ciphertext = encrypt_backup(plaintext)
        # Stabilna nazwa pozwala wznowić po awarii; oryginalna nazwa nie wycieka.
        target_name = f"backups/migrated/{hashlib.sha256(name.encode()).hexdigest()}.json.fernet"
        if not target.exists(target_name):
            saved = target.save(target_name, ContentFile(ciphertext))
            if saved != target_name:
                target.delete(saved)
                raise CommandError("Równoległy zapis kopii; ponów migrację.")
        with target.open(target_name, "rb") as stream:
            recovered = decrypt_backup(read_backup(stream, encrypted=True))
        if recovered != plaintext:
            raise CommandError("Niezgodna zawartość kopii; stare dane pozostają bez zmian.")
        if delete_source:
            if digest(source, name) != hashlib.sha256(plaintext).digest():
                raise CommandError("Źródło kopii zmieniło się; nie usuwam go.")
            source.delete(name)
