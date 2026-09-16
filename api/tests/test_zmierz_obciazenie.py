"""
Przyrząd pomiarowy do obciążenia: liczenie p95 i werdykt wobec SLO.

Kategoria ryzyka: FAŁSZYWY POMIAR. Narzędzie, które liczy źle, jest gorsze od
braku narzędzia: pokazuje zielone „mieści się w SLO" i na tej podstawie
podejmuje się decyzje o zasobach. Tak samo jak przy `zmierz_skale`, gdzie
przyrząd raz pokazywał stan sprzed zmiany - bot działał, kłamał pomiar.

Sam ruch HTTP nie jest tu testowany: to biblioteka standardowa i sieć.
Testujemy część, która z liczb robi werdykt.
"""

import pytest

from api.management.commands.zmierz_obciazenie import (
    PROGI_P95,
    ocena,
    podsumuj,
    profil,
    wyslij,
)


def test_p95_bierze_wartosc_z_ogona_a_nie_srednia():
    # Dziewiętnaście szybkich odpowiedzi i jedna wolna: średnia by ją zatarła,
    # p95 ma ją pokazać - o to w tym pomiarze chodzi.
    pomiary = {"widget: FAQ": [(200, 100.0)] * 19 + [(200, 5000.0)]}

    wynik = podsumuj(pomiary)["widget: FAQ"]

    assert wynik["ile"] == 20
    assert wynik["p50"] == 100.0
    assert wynik["p95"] == 5000.0
    assert wynik["max"] == 5000.0


def test_podsumowanie_liczy_kody_odpowiedzi():
    pomiary = {"panel: pulpit": [(200, 10.0), (200, 20.0), (429, 5.0), (500, 30.0)]}

    wynik = podsumuj(pomiary)["panel: pulpit"]

    assert wynik["kody"] == {200: 2, 429: 1, 500: 1}


def test_przekroczony_prog_p95_jest_zglaszany():
    prog = PROGI_P95["widget"]
    pomiary = {"widget: FAQ": [(200, prog + 100.0)] * 20}

    uwagi = ocena(podsumuj(pomiary), {"widget: FAQ": "widget"})

    assert len(uwagi) == 1
    assert "p95" in uwagi[0]


def test_panel_ma_luzniejszy_prog_niz_widget():
    # Ten sam czas: dla widgetu poza progiem, dla panelu w progu. Gdyby
    # narzędzie miało jeden próg dla wszystkiego, jedno z dwóch kłamałoby.
    czasy = {"x": [(200, 600.0)] * 20}

    assert ocena(podsumuj(czasy), {"x": "widget"})
    assert not ocena(podsumuj(czasy), {"x": "panel"})


def test_pojedynczy_blad_serwera_nie_wywraca_werdyktu_ale_seria_tak():
    jeden = {"panel: pulpit": [(500, 10.0)] + [(200, 10.0)] * 999}
    seria = {"panel: pulpit": [(500, 10.0)] * 10 + [(200, 10.0)] * 990}

    assert not ocena(podsumuj(jeden), {"panel: pulpit": "panel"})
    assert any("5xx" in uwaga for uwaga in ocena(podsumuj(seria), {"panel: pulpit": "panel"}))


def test_brak_odpowiedzi_nie_jest_liczony_jako_blad_serwera():
    # Kod 0 znaczy "nie doszło" - zerwane połączenie albo przekroczony czas.
    # To awaria pomiaru albo sieci, nie odpowiedź 5xx aplikacji; ma być widoczna
    # w rozkładzie kodów, ale nie ma udawać błędu serwera.
    pomiary = {"widget: FAQ": [(0, 30000.0)] * 5 + [(200, 10.0)] * 95}

    wynik = podsumuj(pomiary)["widget: FAQ"]

    assert wynik["kody"][0] == 5
    uwagi = ocena({"widget: FAQ": wynik}, {"widget: FAQ": "widget"})
    assert not any("5xx" in uwaga for uwaga in uwagi)


def test_profil_bez_tokenu_mierzy_tylko_widget():
    scenariusze = profil(klucz="klucz-firmy", token="")

    assert {s.obszar for s in scenariusze} == {"widget"}
    assert all(s.naglowki.get("X-API-Key") == "klucz-firmy" for s in scenariusze)


def test_profil_bez_klucza_i_tokenu_jest_pusty():
    assert profil(klucz="", token="") == []


def test_profil_z_tokenem_dokłada_ekrany_panelu():
    scenariusze = profil(klucz="klucz-firmy", token="jwt")

    obszary = [s.obszar for s in scenariusze]
    assert obszary.count("panel") == 3
    assert all(
        s.naglowki.get("Authorization") == "Bearer jwt" for s in scenariusze if s.obszar == "panel"
    )


def test_adres_spoza_http_jest_odrzucany():
    # `urlopen` otwiera także `file:` - bez tej kontroli `--adres file:///etc/passwd`
    # zamieniłby przyrząd pomiarowy w czytnik plików z maszyny, na której działa.
    scenariusz = profil(klucz="klucz", token="")[0]

    with pytest.raises(ValueError):
        wyslij("file:///etc", scenariusz)
