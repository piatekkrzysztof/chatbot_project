"""
Sygnały muszą być podłączone przy starcie aplikacji, nie przez testy.

Import `documents.signals` zniknął z `DocumentsConfig.ready()` w porządkach
długu ruff (PR #21, 4.09.2026) - ruff uznał go za nieużywany. Od tamtej pory
ani proces web, ani worker nie podłączały sygnału: dokument wgrany w panelu
zapisywał treść, ale nie dostawał embeddingów.

Żaden test tego nie złapał, bo w procesie pytest moduł i tak jest wczytany:
wystarczy jeden `patch("documents.signals.enqueue")` gdziekolwiek w pakiecie.
Dlatego sprawdzamy w osobnym procesie, który startuje Django tak jak web
i worker, bez niczego zaimportowanego wcześniej.

Od 2.8.1 na sygnałach wisi też kasowanie plików z magazynu, przeniesione
z widoku panelu. Odłączony sygnał znaczy tym razem, że plik, który klient
kazał usunąć, zostaje w magazynie - i nikt się o tym nie dowie, bo panel
pokazuje, że dokumentu nie ma.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

KATALOG_PROJEKTU = Path(__file__).resolve().parents[2]

WYMAGANE = {
    "documents.signals.handle_new_document": ("dokumenty z panelu nie dostaną embeddingów"),
    "documents.signals.usun_plik_dokumentu": (
        "usunięty dokument zostawi swój plik w prywatnym magazynie"
    ),
    "accounts.signals.usun_pliki_brandingu": ("usunięta firma zostawi logo i awatar w magazynie"),
    "accounts.signals.usun_zastapione_pliki_brandingu": (
        "wymienione logo zostawi poprzedni plik w magazynie"
    ),
}

SKRYPT = textwrap.dedent(
    """
    import os
    import weakref

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings")
    import django

    django.setup()
    from django.db.models.signals import post_delete, post_save, pre_save

    odbiorcy = set()
    for sygnal in (post_save, post_delete, pre_save):
        for wpis in sygnal.receivers:
            ref = wpis[1]
            obiekt = ref() if isinstance(ref, weakref.ReferenceType) else ref
            odbiorcy.add(f"{getattr(obiekt, '__module__', '')}.{getattr(obiekt, '__name__', '')}")
    for nazwa in sorted(odbiorcy):
        print(nazwa)
    """
)


def test_sygnaly_podlaczone_przy_starcie_django():
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
    podlaczone = set(wynik.stdout.split())
    brakujace = {nazwa: skutek for nazwa, skutek in WYMAGANE.items() if nazwa not in podlaczone}
    assert not brakujace, "Sygnały niepodłączone przy starcie: " + "; ".join(
        f"{nazwa} ({skutek})" for nazwa, skutek in brakujace.items()
    )
