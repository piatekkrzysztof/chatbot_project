"""
Wersja Pythona na produkcji, w CI i w obrazie jest jedna.

Skany przed wydaniem (11.10.2026, F05/F12) pokazały, że produkcja stała na
3.11.1 z grudnia 2022, a CI testował na najnowszej 3.11. Kod przechodził testy
na wersji, na której nie działał, a produkcja nie miała kilku lat poprawek
bezpieczeństwa CPythona - w tym urllib.parse, na którym stoi ochrona przed
SSRF przy imporcie stron.

Na produkcji wersję ustawia PYTHON_VERSION w panelu Rendera (usługi nie są
synchronizowane z render.yaml), więc test nie sprawdzi samej produkcji. Pilnuje,
żeby zapis w repozytorium był jeden, zgodny z CI i obrazem, i żeby nie cofnął
się poniżej wersji sprawdzonej przy skanie.
"""

import re
from pathlib import Path

import yaml

KATALOG = Path(__file__).resolve().parents[2]
NAJSTARSZA_DOPUSZCZALNA = (3, 11, 17)


def _wersja(tekst):
    return tuple(int(c) for c in tekst.strip().split("."))


def _wersje_renderu():
    opis = yaml.safe_load((KATALOG / "render.yaml").read_text(encoding="utf-8"))
    return {
        usluga["name"]: str(zmienna["value"])
        for usluga in opis["services"]
        for zmienna in usluga.get("envVars", [])
        if zmienna.get("key") == "PYTHON_VERSION"
    }


def test_wszystkie_uslugi_renderu_i_runtime_maja_te_sama_wersje():
    wersje = _wersje_renderu()
    assert {"chatbot-backend", "celery-worker"} <= wersje.keys()
    runtime = (KATALOG / "runtime.txt").read_text(encoding="utf-8").strip()
    assert set(wersje.values()) == {runtime.removeprefix("python-")}


def test_wersja_nie_starsza_niz_sprawdzona_przy_skanie():
    for usluga, wersja in _wersje_renderu().items():
        assert _wersja(wersja) >= NAJSTARSZA_DOPUSZCZALNA, usluga


def test_ci_i_obraz_testuja_te_sama_galaz_co_produkcja():
    galaz = ".".join(next(iter(_wersje_renderu().values())).split(".")[:2])
    ci = (KATALOG / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert set(re.findall(r"python-version:\s*'([\d.]+)'", ci)) == {galaz}
    obraz = (KATALOG / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM python:(\d+\.\d+)-slim", obraz, re.M).group(1) == galaz
