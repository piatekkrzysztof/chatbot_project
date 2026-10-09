"""
Macierz dostępu (F01) - tabela „kto co może" dla ludzi.

Kategoria ryzyka: DOKUMENT, KTÓRY KŁAMIE. Tabela uprawnień czytana przez
klienta albo audytora jest gorsza niż jej brak, jeśli nie zgadza się z tym,
co serwer robi naprawdę. Dlatego docs/macierz-dostepu.md jest generowany
z tego samego kontraktu, który test_kontrakt_dostepu.py sprawdza prawdziwymi
żądaniami, a ten test pilnuje, że plik w repozytorium jest aktualny.
"""

from pathlib import Path

import pytest
from django.conf import settings

from api.kontrakt_dostepu import CZLONEK, KONTO, KONTRAKT, PRACOWNIK, PUBLICZNA, WLASCICIEL
from api.macierz_dostepu import KTO_PRZECHODZI, SCIEZKA_DOKUMENTU, zbuduj_macierz


@pytest.fixture(scope="module")
def macierz():
    return zbuduj_macierz()


def test_dokument_w_repozytorium_jest_aktualny(macierz):
    zapisany = (Path(settings.BASE_DIR) / SCIEZKA_DOKUMENTU).read_text(encoding="utf-8")

    assert zapisany.replace("\r\n", "\n") == macierz, (
        "docs/macierz-dostepu.md nie zgadza się z kontraktem dostępu. "
        "Uruchom: python manage.py macierz_dostepu --zapisz"
    )


def test_kazda_operacja_kontraktu_jest_w_tabeli_z_opisem(macierz):
    wiersze = [linia for linia in macierz.splitlines() if linia.startswith("| `")]

    assert len(wiersze) == len(KONTRAKT)
    bez_opisu = [w for w in wiersze if w.split(" | ")[1].strip() == "-"]
    assert not bez_opisu, (
        "Operacja bez opisu - dodaj summary w extend_schema widoku albo wpis "
        f"w OPISY_UZUPELNIAJACE: {bez_opisu}"
    )


def test_tabela_mowi_to_samo_co_polityki():
    """Kolumny: anonim, sam klucz widgetu, podgląd, pracownik, właściciel."""
    assert KTO_PRZECHODZI[PUBLICZNA] == (True, True, True, True, True)
    # Bez logowania i z samym jawnym kluczem - nic poza publicznymi.
    for polityka in (KONTO, CZLONEK, PRACOWNIK, WLASCICIEL):
        assert KTO_PRZECHODZI[polityka][:2] == (False, False)
    assert KTO_PRZECHODZI[PRACOWNIK][2] is False  # podgląd nie zmienia
    assert KTO_PRZECHODZI[WLASCICIEL][3] is False  # pracownik nie ma uprawnień właściciela
    # Właściciel przechodzi kontrolę uprawnień każdej operacji.
    assert all(kto[4] for kto in KTO_PRZECHODZI.values())
