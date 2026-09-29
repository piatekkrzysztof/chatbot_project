"""
Sprzątanie archiwum kopii: co znika, a co zostaje zawsze.

Kategoria ryzyka: SKASOWANA OSTATNIA KOPIA. Retencja archiwum jest jedyną
operacją w systemie, która usuwa dane nieodwracalnie i bez żadnej drugiej
szansy - kopii zapasowej kopii nie ma. Pomyłka w warunku nie objawia się
niczym, dopóki nie przyjdzie dzień, w którym kopia jest potrzebna.

Najważniejszy test w tym pliku nie dotyczy wieku, tylko minimum: przy
zatrzymanym tworzeniu kopii sam warunek wieku wyzerowałby archiwum do końca -
i to dokładnie wtedy, gdy kopii zaczyna brakować. Że tworzenie potrafi się
zatrzymać po cichu, wiemy nie z rozważań: trzy zadania z harmonogramu nie
działały tu przez tygodnie, a wszystko wyglądało poprawnie.
"""

from datetime import UTC, datetime, timedelta

import pytest

from accounts import retencja_kopii
from accounts.retencja_kopii import MINIMUM_KOPII, OKRESY, do_usuniecia, usun

TERAZ = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


class AtrapaMagazynu:
    """Magazyn, który zna prefiksy - inaczej niż atrapa z testów kontroli kopii."""

    def __init__(self, obiekty):
        self.obiekty = list(obiekty)
        self.usuniete = []
        self.padnij_na = set()

    def listdir(self, katalog):
        prefiks = f"{katalog}/"
        return [], [o[len(prefiks) :] for o in self.obiekty if o.startswith(prefiks)]

    def delete(self, nazwa):
        if nazwa in self.padnij_na:
            raise OSError("magazyn nie odpowiada")
        self.obiekty.remove(nazwa)
        self.usuniete.append(nazwa)


def pelna(wiek):
    czas = TERAZ - wiek
    return f"full-backups/full-{czas:%Y%m%d-%H%M%S}-{'a' * 32}.saas"


def dzienna(wiek):
    czas = TERAZ - wiek
    return f"backups/kopia-{czas:%Y%m%d-%H%M%S}-{'b' * 32}.json.fernet"


DZIEN = timedelta(days=1)


class TestWieku:
    def test_granica_okresu(self):
        okres = OKRESY["pelna"]
        # Cztery kopie, żeby minimum trzech nie zasłoniło reguły wieku.
        magazyn = AtrapaMagazynu(
            [
                pelna(timedelta()),
                pelna(10 * DZIEN),
                pelna(20 * DZIEN),
                pelna(okres - timedelta(hours=1)),
                pelna(okres + timedelta(hours=1)),
            ]
        )

        nazwy = do_usuniecia(magazyn, "pelna", TERAZ)

        assert nazwy == [pelna(okres + timedelta(hours=1))]

    def test_kazde_archiwum_ma_swoj_okres(self):
        # 100 dni: dla dziennych ponad próg (90), dla pełnych jeszcze nie (365).
        magazyn = AtrapaMagazynu(
            [pelna(100 * DZIEN), dzienna(100 * DZIEN)]
            + [pelna(i * DZIEN) for i in range(3)]
            + [dzienna(i * DZIEN) for i in range(3)]
        )

        assert do_usuniecia(magazyn, "pelna", TERAZ) == []
        assert do_usuniecia(magazyn, "dzienna", TERAZ) == [dzienna(100 * DZIEN)]


class TestMinimum:
    """Najważniejsza reguła: ostatnie kopie zostają bez względu na wiek."""

    def test_trzy_najnowsze_zostaja_nawet_gdy_sa_starozytne(self):
        # Tworzenie kopii stanęło dwa lata temu. Sam wiek kazałby usunąć
        # wszystko - czyli zostawić firmę bez jednej kopii w chwili, w której
        # najbardziej ich potrzebuje.
        magazyn = AtrapaMagazynu([pelna((700 + i) * DZIEN) for i in range(5)])

        nazwy = do_usuniecia(magazyn, "pelna", TERAZ)

        assert len(nazwy) == 5 - MINIMUM_KOPII
        zostaja = [o for o in magazyn.obiekty if o not in nazwy]
        assert zostaja == sorted(zostaja, reverse=True)[:MINIMUM_KOPII]

    def test_archiwum_mniejsze_niz_minimum_zostaje_nietkniete(self):
        magazyn = AtrapaMagazynu([pelna(900 * DZIEN), pelna(800 * DZIEN)])

        assert do_usuniecia(magazyn, "pelna", TERAZ) == []

    def test_puste_archiwum_nie_wywraca_sie(self):
        assert do_usuniecia(AtrapaMagazynu([]), "pelna", TERAZ) == []


class TestCzegoNieRuszamy:
    def test_obcy_plik_w_katalogu_kopii_zostaje(self):
        # Coś wgranego ręcznie albo zostawionego przez inne narzędzie. Magazyn
        # kopii nie jest miejscem na sprzątanie z rozpędu.
        magazyn = AtrapaMagazynu(
            [pelna((400 + i) * DZIEN) for i in range(4)]
            + ["full-backups/notatka.txt", "full-backups/full-cos-innego.saas"]
        )

        nazwy = do_usuniecia(magazyn, "pelna", TERAZ)

        assert all(n.endswith(".saas") for n in nazwy)
        assert "full-backups/notatka.txt" not in nazwy
        assert "full-backups/full-cos-innego.saas" not in nazwy

    def test_obcy_plik_z_data_w_nazwie_tez_zostaje(self):
        # Trudniejszy przypadek: nazwa niesie datę, więc sam warunek wieku by
        # go nie obronił. Rozstrzyga wzorzec nazwy, którym zapisujemy kopie -
        # bez niego retencja skasowałaby cudzy eksport sprzed lat.
        obcy = "full-backups/eksport-20240101-000000-ksiegowosc.zip"
        magazyn = AtrapaMagazynu([obcy] + [pelna((500 + i) * DZIEN) for i in range(4)])

        assert obcy not in do_usuniecia(magazyn, "pelna", TERAZ)

    def test_nazwa_bez_czytelnej_daty_zostaje(self):
        magazyn = AtrapaMagazynu(
            [f"full-backups/full-99999999-999999-{'c' * 32}.saas"]
            + [pelna((500 + i) * DZIEN) for i in range(4)]
        )

        assert f"full-backups/full-99999999-999999-{'c' * 32}.saas" not in do_usuniecia(
            magazyn, "pelna", TERAZ
        )


class TestWykonania:
    def test_bez_wykonaj_nic_nie_znika(self):
        magazyn = AtrapaMagazynu([pelna((400 + i) * DZIEN) for i in range(5)])

        nazwy = usun(magazyn, "pelna", teraz=TERAZ)

        assert nazwy and magazyn.usuniete == []

    def test_z_wykonaj_znika_dokladnie_to_co_wyliczone(self):
        magazyn = AtrapaMagazynu([pelna((400 + i) * DZIEN) for i in range(5)])
        zapowiedziane = do_usuniecia(magazyn, "pelna", TERAZ)

        usuniete = usun(magazyn, "pelna", teraz=TERAZ, wykonaj=True)

        assert usuniete == zapowiedziane == magazyn.usuniete
        assert len(magazyn.obiekty) == MINIMUM_KOPII

    def test_jedna_nieudana_nie_zatrzymuje_reszty_ani_nie_klamie(self, caplog):
        magazyn = AtrapaMagazynu([pelna((400 + i) * DZIEN) for i in range(5)])
        oporna = do_usuniecia(magazyn, "pelna", TERAZ)[0]
        magazyn.padnij_na = {oporna}

        usuniete = usun(magazyn, "pelna", teraz=TERAZ, wykonaj=True)

        assert oporna not in usuniete
        assert len(usuniete) == 1
        assert oporna in caplog.text


def test_okresy_sa_tymi_zatwierdzonymi():
    """
    Zmiana okresu kasowania kopii jest decyzją właściciela, nie porządkami
    w kodzie. Testy granic biorą wartość ze stałej, więc same nie zauważą,
    że ktoś tę stałą przesunął.
    """
    assert retencja_kopii.OKRESY == {
        "pelna": timedelta(days=365),
        "dzienna": timedelta(days=90),
    }
    assert retencja_kopii.MINIMUM_KOPII == 3
