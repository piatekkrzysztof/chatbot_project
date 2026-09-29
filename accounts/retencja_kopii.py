"""
Sprzątanie archiwum kopii zapasowych.

Do 2.15.0 nic nie usuwało starych kopii. Przy dzisiejszej skali to jeszcze nie
problem miejsca, ale problem danych: **kopia niesie dane osobowe klientów,
także tych, którzy odeszli**. Zdanie „usunęliśmy Pana dane" przestaje być
prawdziwe, jeśli leżą w kopii sprzed dwóch lat, a retencja z F20 kasuje je
wyłącznie w bazie.

Trzy zasady, na których to stoi
-------------------------------

**1. Wiek.** Kopie starsze niż okres przechowywania idą do usunięcia.

**2. Minimum, które zostaje ZAWSZE.** Niezależnie od wieku zostawiamy trzy
najnowsze kopie w każdym archiwum. Bez tej reguły sam wiek wystarczyłby, żeby
przy zatrzymanym tworzeniu kopii archiwum wyzerowało się do końca - i to
właśnie wtedy, gdy kopii zaczyna brakować. Dokładnie taka awaria zdarzyła się
tu już raz: trzy zadania z harmonogramu nie działały przez tygodnie, a wszystko
wyglądało poprawnie. Monitor braku przebiegów krzyknie, ale krzyk nie przywróci
skasowanego pliku.

**3. Nie ruszamy tego, czego nie rozpoznajemy.** Usuwamy wyłącznie obiekty
pasujące do wzorców nazw, którymi sami zapisujemy kopie. Cokolwiek innego leży
w tym samym miejscu - wgrane ręcznie, zostawione przez inne narzędzie - zostaje
nietknięte. Magazyn kopii nie jest miejscem na sprzątanie z rozpędu.

Okresy są własnością właściciela, tak samo jak przy retencji danych. Zmiana
którejkolwiek wartości zmienia zachowanie kasowania i jest decyzją, nie
porządkami w kodzie - pilnuje tego osobny test.
"""

import logging
import re
from datetime import UTC, datetime, timedelta

from accounts.full_backups import KATALOG_PELNYCH_KOPII, NAZWA_PELNEJ_KOPII

logger = logging.getLogger(__name__)

NAZWA_DZIENNEJ_KOPII = re.compile(r"kopia-[0-9]{8}-[0-9]{6}-[a-f0-9]{32}\.json\.fernet\Z")
CZAS_W_NAZWIE = re.compile(r"-([0-9]{8}-[0-9]{6})-")

# Ile trzymamy, licząc od czasu w nazwie kopii.
OKRESY = {
    # Rok: tyle samo, co dziennik audytowy. Kopia starsza niż rok nie pomoże
    # przy żadnym pytaniu, na które dziennik już nie odpowiada, a niesie dane
    # osób, które dawno odeszły.
    "pelna": timedelta(days=365),
    # Kopie dzienne powstają rzadziej i służą krótkiemu odtworzeniu, nie
    # archiwum. Kwartał wystarcza na wykrycie i naprawienie szkody.
    "dzienna": timedelta(days=90),
}

# Zostaje zawsze, bez względu na wiek.
MINIMUM_KOPII = 3

ARCHIWA = {
    "pelna": (KATALOG_PELNYCH_KOPII, NAZWA_PELNEJ_KOPII),
    "dzienna": ("backups", NAZWA_DZIENNEJ_KOPII),
}


def czas_z_nazwy(nazwa):
    """Czas z nazwy pliku; None, gdy nazwa go nie niesie."""
    dopasowanie = CZAS_W_NAZWIE.search(nazwa)
    if not dopasowanie:
        return None
    try:
        return datetime.strptime(dopasowanie.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def do_usuniecia(magazyn, rodzaj, teraz=None):
    """
    Nazwy kopii objętych regułą. Niczego nie usuwa.

    Nazwę nadaje ten, kto zapisuje plik, więc teoretycznie da się ją podrobić.
    Przy kasowaniu działa to jednak w bezpieczną stronę: plik z datą udającą
    świeżą zostanie, a nie zniknie. Odwrotnego ryzyka nie ma.
    """
    teraz = teraz or datetime.now(UTC)
    katalog, wzorzec = ARCHIWA[rodzaj]
    try:
        _, nazwy = magazyn.listdir(katalog)
    except Exception:
        logger.exception("Nie można odczytać listy kopii z katalogu %s", katalog)
        raise

    rozpoznane = []
    for nazwa in nazwy:
        if not wzorzec.fullmatch(nazwa):
            continue
        czas = czas_z_nazwy(nazwa)
        if czas is not None:
            rozpoznane.append((czas, nazwa))

    # Najnowsze na początku: minimum liczymy od góry, niezależnie od wieku.
    rozpoznane.sort(reverse=True)
    chronione = {nazwa for _, nazwa in rozpoznane[:MINIMUM_KOPII]}
    prog = teraz - OKRESY[rodzaj]
    return [
        f"{katalog}/{nazwa}" for czas, nazwa in rozpoznane if czas < prog and nazwa not in chronione
    ]


def usun(magazyn, rodzaj, *, teraz=None, wykonaj=False):
    """
    Usuwa kopie objęte regułą i zwraca ich nazwy.

    Bez `wykonaj` tylko wylicza. Domyślna próba, a nie domyślne kasowanie:
    to jedyne miejsce w systemie, które usuwa dane nieodwracalnie i bez
    możliwości odtworzenia z czegokolwiek - kopia zapasowa kopii nie istnieje.
    """
    nazwy = do_usuniecia(magazyn, rodzaj, teraz)
    if not wykonaj:
        return nazwy
    usuniete = []
    for nazwa in nazwy:
        try:
            magazyn.delete(nazwa)
        except Exception:
            # Jedna nieudana nie może zatrzymać reszty ani udawać sukcesu.
            logger.exception("Nie udało się usunąć kopii %s", nazwa)
            continue
        usuniete.append(nazwa)
    return usuniete
