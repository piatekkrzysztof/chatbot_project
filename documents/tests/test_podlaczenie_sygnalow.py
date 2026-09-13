"""
Sygnał dokumentu musi być podłączony przy starcie aplikacji, nie przez testy.

Import `documents.signals` zniknął z `DocumentsConfig.ready()` w porządkach
długu ruff (PR #21, 4.09.2026) - ruff uznał go za nieużywany. Od tamtej pory
ani proces web, ani worker nie podłączały sygnału: dokument wgrany w panelu
zapisywał treść, ale nie dostawał embeddingów.

Żaden test tego nie złapał, bo w procesie pytest moduł i tak jest wczytany:
wystarczy jeden `patch("documents.signals.enqueue")` gdziekolwiek w pakiecie.
Dlatego sprawdzamy w osobnym procesie, który startuje Django tak jak web
i worker, bez niczego zaimportowanego wcześniej.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

KATALOG_PROJEKTU = Path(__file__).resolve().parents[2]

SKRYPT = textwrap.dedent(
    """
    import os
    import weakref

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings")
    import django

    django.setup()
    from django.db.models.signals import post_save

    odbiorcy = set()
    for wpis in post_save.receivers:
        ref = wpis[1]
        obiekt = ref() if isinstance(ref, weakref.ReferenceType) else ref
        odbiorcy.add(f"{getattr(obiekt, '__module__', '')}.{getattr(obiekt, '__name__', '')}")
    print("PODLACZONY" if "documents.signals.handle_new_document" in odbiorcy else "BRAK")
    """
)


def test_sygnal_dokumentu_podlaczony_przy_starcie_django():
    wynik = subprocess.run(
        [sys.executable, "-c", SKRYPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=KATALOG_PROJEKTU,
        env=os.environ.copy(),
    )

    assert wynik.returncode == 0, wynik.stderr[-2000:]
    assert wynik.stdout.strip().splitlines()[-1] == "PODLACZONY", (
        "documents.signals nie jest importowany w DocumentsConfig.ready() - "
        "dokumenty z panelu nie dostaną embeddingów"
    )
