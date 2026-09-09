"""
Ostrzeżenie o ulotnym magazynie plików.

Render kasuje dysk kontenera przy każdym wdrożeniu. Dopóki nie ma skonfigurowanego
magazynu obiektowego, logotypy i awatary wgrane przez klientów znikają — i to bez
żadnego błędu, bo zapis się udaje. Objawia się dopiero po kilku dniach jako
"logo samo zniknęło", co wygląda na losową awarię i fatalnie wypada u klienta.

Wcześniej ustawienia wskazywały S3, ale przez usunięte w Django 5.1
DEFAULT_FILE_STORAGE było to ignorowane. Cisza w takiej sytuacji jest gorsza
niż błąd, dlatego stan bez magazynu jest teraz jawnie raportowany.
"""

from django.conf import settings
from django.core.checks import Warning, register
from django.core.files.storage import storages

from chatbot_project.storage import PrivateS3Storage


@register()
def ephemeral_file_storage(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    if getattr(settings, "USE_OBJECT_STORAGE", True):
        return []

    return [
        Warning(
            "Wgrywane pliki trafiają na dysk kontenera, który znika przy wdrożeniu.",
            hint=(
                "Ustaw AWS_STORAGE_BUCKET_NAME, AWS_ACCESS_KEY_ID i "
                "AWS_SECRET_ACCESS_KEY (dla Cloudflare R2 lub innego magazynu "
                "zgodnego z S3 dodaj AWS_S3_ENDPOINT_URL). Bez tego logotypy "
                "i dokumenty klientów przepadają przy każdym deployu."
            ),
            id="documents.W001",
        )
    ]


@register(deploy=True)
def private_storage_readiness(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    warnings = []
    for alias, code in (
        ("private_documents", "documents.W002"),
        ("private_backups", "documents.W003"),
    ):
        if not isinstance(storages[alias], PrivateS3Storage):
            warnings.append(
                Warning(
                    f"{alias}: brak prywatnego magazynu obiektowego; nowy zapis jest niedostępny.",
                    hint="Skonfiguruj oddzielne buckety i poświadczenia na web oraz workerze.",
                    id=code,
                )
            )
    if not settings.BACKUP_ENCRYPTION_KEY:
        warnings.append(
            Warning("Brak BACKUP_ENCRYPTION_KEY; kopie są zablokowane.", id="documents.W004")
        )
    if settings.ALLOW_LEGACY_DOCUMENT_READS:
        warnings.append(
            Warning(
                "Odczyt dokumentów ze starego magazynu jest nadal dozwolony.",
                hint="Po migracji ustaw ALLOW_LEGACY_DOCUMENT_READS=false.",
                id="documents.W005",
            )
        )
    return warnings
