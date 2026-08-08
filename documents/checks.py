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
