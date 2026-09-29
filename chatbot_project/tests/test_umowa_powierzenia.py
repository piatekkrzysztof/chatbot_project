"""
Umowa powierzenia musi opisywać ten system, a nie poprzedni.

Kategoria ryzyka: DOKUMENT, KTÓRY PRZESTAŁ BYĆ PRAWDZIWY. Umowa powierzenia
trafia do audytu klienta i do jego rejestru czynności przetwarzania. Klient
nie ma jak sprawdzić, czy lista podprzetwarzających jest aktualna - wierzy nam
na słowo. Dodanie szóstej usługi bez dopisania jej do załącznika B zamienia
zdanie „to są wszyscy" w nieprawdę, a art. 28 ust. 2 RODO daje klientowi prawo
sprzeciwu wobec zmiany, o której musi się dowiedzieć.

Ten sam mechanizm zawiódł już w rejestrze roadmapy: dokument opisywał stan
sprzed dwóch tygodni i nikt tego nie widział, bo nic tego nie sprawdzało.
Tam kosztowało to złą kolejność pracy. Tutaj kosztowałoby wiarygodność wobec
klienta i organu.
"""

import re
from datetime import timedelta
from pathlib import Path

from accounts import retencja_kopii

KATALOG = Path(__file__).resolve().parents[2]
UMOWA = KATALOG / "docs" / "umowa-powierzenia.md"
PRZEPLYWY = KATALOG / "docs" / "przeplywy-danych.md"

NAGLOWEK_PODPRZETWARZAJACY = "## Kto przetwarza dane poza naszą bazą"
NAGLOWEK_ZALACZNIK_B = "## Załącznik B. Podprzetwarzający"


def pierwsza_kolumna_tabeli(tekst, naglowek):
    """
    Pierwsza kolumna pierwszej tabeli pod danym nagłówkiem.

    Bez wiersza nagłówkowego tabeli i bez wiersza z myślnikami. Zatrzymujemy
    się na pierwszej linii, która nie zaczyna się od `|`, więc kolejna tabela
    w tym samym rozdziale nie wpada do wyniku.
    """
    assert naglowek in tekst, f"brak rozdziału: {naglowek}"
    po_naglowku = tekst.split(naglowek, 1)[1]

    wiersze = []
    w_tabeli = False
    for linia in po_naglowku.splitlines():
        linia = linia.strip()
        if not linia.startswith("|"):
            if w_tabeli:
                break
            continue
        w_tabeli = True
        wiersze.append(linia)

    nazwy = []
    for linia in wiersze[2:]:  # pomijamy nagłówek tabeli i myślniki
        komorki = [k.strip() for k in linia.strip("|").split("|")]
        if komorki and komorki[0]:
            nazwy.append(komorki[0])
    return nazwy


def test_zalacznik_b_wymienia_dokladnie_tych_podprzetwarzajacych_co_przeplywy():
    """
    Jedna lista w dwóch plikach rozjedzie się przy pierwszej zmianie dostawcy.

    Przepływy danych są dokumentem roboczym i to je aktualizujemy najpierw.
    Umowa jest dokumentem, który widzi klient - i właśnie dlatego zapomnienie
    o niej jest łatwe, a kosztowne.
    """
    z_przeplywow = pierwsza_kolumna_tabeli(
        PRZEPLYWY.read_text(encoding="utf-8"), NAGLOWEK_PODPRZETWARZAJACY
    )
    z_umowy = pierwsza_kolumna_tabeli(UMOWA.read_text(encoding="utf-8"), NAGLOWEK_ZALACZNIK_B)

    assert len(z_przeplywow) >= 5, "tabela podprzetwarzających nagle zmalała - zmienił się format?"
    assert set(z_umowy) == set(z_przeplywow)


def test_umowa_podaje_te_okresy_kopii_co_kod():
    """
    § 9 obiecuje klientowi, kiedy jego dane znikną z kopii zapasowych.

    To jest jedyne zdanie w umowie, które mówi o danych usuniętych na żądanie,
    a mimo to wciąż istniejących. Rozminięcie się z `retencja_kopii.OKRESY`
    oznaczałoby, że obiecujemy termin, którego nic nie pilnuje.
    """
    tekst = UMOWA.read_text(encoding="utf-8")
    paragraf = tekst.split("## § 9.", 1)[1].split("## § 10.", 1)[0]
    # Sam akapit o kopiach, nie cały paragraf: wyżej jest jeszcze termin
    # 30 dni na wybór zwrotu albo usunięcia i nie ma nic wspólnego z rotacją.
    paragraf = paragraf.split("**Kopie zapasowe są wyjątkiem", 1)[1]

    dni = {int(x) for x in re.findall(r"\*\*(\d+) dni\*\*", paragraf)}

    assert retencja_kopii.OKRESY["pelna"] == timedelta(days=365)
    assert retencja_kopii.OKRESY["dzienna"] == timedelta(days=90)
    assert dni == {365, 90}


def test_umowa_podaje_domyslny_okres_retencji_rozmow_zgodny_z_modelem():
    """Załącznik A nazywa konkretną liczbę dni jako domyślną - musi być ta z modelu."""
    from accounts.models import Tenant

    domyslny = Tenant._meta.get_field("data_retention_days").default
    tekst = UMOWA.read_text(encoding="utf-8")

    assert domyslny == 90
    assert f"domyślnie {domyslny} dni" in tekst
