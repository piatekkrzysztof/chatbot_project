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

Od 29.09.2026 sprawdzamy nie tylko harmonogram. Zadanie zlecane z kodu
(`enqueue`) nie ma wpisu w harmonogramie, więc pierwsza wersja tego pliku go
nie obejmowała - a milknie dokładnie tak samo i w gorszym momencie, bo takie
zadania zleca się przy zdarzeniu, na które właśnie czekamy.

Sprawdzamy w osobnym procesie, który startuje Django i Celery tak jak worker.
W procesie pytest moduły są już wczytane przez inne testy, więc rejestracja
wyszłaby poprawna niezależnie od tego, co robi autodiscovery. To nie jest
drobiazg: asercja `"nazwa" in app.tasks` napisana wprost w teście przechodzi
nawet wtedy, gdy worker tego zadania nie zna.
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

    # Zadania zlecane z kodu: nie ma ich w harmonogramie, a muszą być znane
    # tak samo. Szukamy ich w źródłach, nie przez import - import w tym
    # procesie rejestrowałby je i zacierał to, czego właśnie szukamy.
    import ast
    import pathlib

    for plik in sorted(pathlib.Path("accounts").glob("*.py")):
        drzewo = ast.parse(plik.read_text(encoding="utf-8"))
        for wezel in drzewo.body:
            if not isinstance(wezel, ast.FunctionDef):
                continue
            dekoratory = {
                d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
                for d in wezel.decorator_list
            }
            if "shared_task" not in dekoratory:
                continue
            zadanie = f"accounts.{plik.stem}.{wezel.name}"
            print(("ZNANE " if zadanie in znane else "BRAK  ") + zadanie)
    """
)


def test_kazde_zadanie_jest_zarejestrowane():
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
        "Zadania, których worker nie zna - zlecający je beat albo kod dostanie "
        "'Received unregistered task' i nic więcej: " + ", ".join(brakujace)
    )


def test_harmonogram_nie_jest_pusty():
    # Kontrola pozytywna: pusty harmonogram przeszedłby test wyżej bez problemu,
    # bo nie ma wtedy żadnego zadania do sprawdzenia.
    from chatbot_project.celery import app

    assert len(app.conf.beat_schedule) >= 8


def test_skrypt_znajduje_takze_zadania_spoza_harmonogramu():
    """
    Druga kontrola pozytywna, dla części dopisanej 29.09.2026.

    Gdyby wyszukiwanie po źródłach przestało cokolwiek znajdować - inna nazwa
    dekoratora, przeniesienie zadań do podkatalogu - test wyżej nadal by
    przechodził, bo lista „BRAK" byłaby pusta z powodu pustej listy zadań.
    """
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
    wypisane = {w[6:] for w in wynik.stdout.splitlines() if w.startswith(("ZNANE", "BRAK"))}
    zlecane_z_kodu = {
        "accounts.tasks_probne.zglos_powtorny_okres_probny",
        "accounts.tasks.powiadom_o_zuzyciu",
    }

    assert zlecane_z_kodu <= wypisane, f"skrypt nie znalazł zadań zlecanych z kodu: {wypisane}"
