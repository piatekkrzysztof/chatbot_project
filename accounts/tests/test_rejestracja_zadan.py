"""
Każde zadanie z harmonogramu musi być znane workerowi.

Kategoria ryzyka: HARMONOGRAM, KTÓRY TYLKO WYGLĄDA NA DZIAŁAJĄCY. Beat zleca
zadania po nazwie i nie sprawdza, czy ktokolwiek je zna. Worker odpowiada
wtedy „Received unregistered task" do logu i zapomina sprawę. Z zewnątrz
wygląda to identycznie jak poprawnie działający harmonogram: zadanie jest
w konfiguracji, beat je wysyła, nikt nie zgłasza błędu.

Celery odkrywa automatycznie wyłącznie moduły nazwane `tasks.py`. Zadania
w modułach o innych nazwach milkną, dopóki ktoś ich nie zaimportuje.

Tak umarły trzy zadania naraz, każde na tygodnie:

  • powiadomienie „subskrypcja wygasła, bot zamilkł" - od 26.08.2026,
  • alarm o odmowach widgetu - od 2.09.2026, ten sam, który powstał PO
    awarii trwającej dobę i niezauważonej,
  • sprzątanie retencyjne - od 17.09.2026.

Znalezione 28.09.2026 przez zajrzenie do logu workera, nie przez testy.
Ten plik istnieje, żeby następnym razem znalazło to CI.

Sprawdzamy w osobnym procesie, który startuje Django i Celery tak jak worker.
W procesie pytest moduły są już wczytane przez inne testy, więc rejestracja
wyszłaby poprawna niezależnie od tego, co robi autodiscovery.
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

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings")
    import django

    django.setup()
    from chatbot_project.celery import app

    # To samo, co robi worker przy starcie.
    app.loader.import_default_modules()
    znane = set(app.tasks)
    for wpis in app.conf.beat_schedule.values():
        zadanie = wpis["task"]
        print(("ZNANE " if zadanie in znane else "BRAK  ") + zadanie)
    """
)


def test_kazde_zadanie_z_harmonogramu_jest_zarejestrowane():
    wynik = subprocess.run(
        [sys.executable, "-c", SKRYPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=KATALOG_PROJEKTU,
        env=os.environ.copy(),
    )

    assert wynik.returncode == 0, wynik.stderr[-2000:]
    linie = [w for w in wynik.stdout.splitlines() if w.startswith(("ZNANE", "BRAK"))]
    assert linie, f"skrypt nie wypisał zadań: {wynik.stdout[-500:]}"

    brakujace = [w.removeprefix("BRAK  ") for w in linie if w.startswith("BRAK")]
    assert not brakujace, (
        "Zadania z harmonogramu, których worker nie zna - beat będzie je zlecał, "
        "a worker odrzucał komunikatem 'Received unregistered task': " + ", ".join(brakujace)
    )


def test_harmonogram_nie_jest_pusty():
    # Kontrola pozytywna: pusty harmonogram przeszedłby test wyżej bez problemu,
    # bo nie ma wtedy żadnego zadania do sprawdzenia.
    from chatbot_project.celery import app

    assert len(app.conf.beat_schedule) >= 8
