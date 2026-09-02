"""
Kody jednorazowe oparte o czas (TOTP, RFC 6238).

Dlaczego bez biblioteki: to nie jest projektowanie kryptografii. RFC 6238
opisuje HMAC-SHA1 ze standardowej biblioteki i ścięcie wyniku do sześciu
cyfr - kilkanaście linii, w pełni wyspecyfikowanych, z OFICJALNYMI wektorami
testowymi. Dzięki nim poprawność da się udowodnić, a nie tylko założyć na
podstawie liczby gwiazdek cudzego repozytorium. Okno tolerancji na rozjazd
zegara i ochronę przed powtórzeniem kodu i tak trzeba napisać samemu -
biblioteka odpowiada wyłącznie na pytanie "czy te sześć cyfr pasuje".

Napięcie w tej decyzji jest realne i nie udaję, że go nie ma: zasada "nie
pisz własnej kryptografii" istnieje nie bez powodu. Waży tu na jej niekorzyść
to, że algorytm jest zamknięty, krótki i sprawdzalny wprost - a każda kolejna
zależność produkcyjna to kolejne miejsce, z którego przyjdzie podatność.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

#: Długość kroku czasowego w sekundach. Trzydzieści to wartość, której
#: oczekują Google Authenticator, 1Password, Aegis i reszta - zmiana oznacza
#: kody niedziałające w aplikacji, którą klient już ma.
KROK_SEKUND = 30

#: Ile cyfr ma kod. Sześć to standard, ośmiu używamy wyłącznie w testach
#: zgodności z wektorami RFC.
CYFR = 6

#: Ile kroków wstecz i wprzód akceptujemy.
#:
#: Zegar telefonu potrafi się rozjechać o kilkanaście sekund, a użytkownik
#: przepisuje kod ręcznie. Zero tolerancji odrzucałoby poprawne kody wpisane
#: sekundę po zmianie. Jeden krok w każdą stronę daje okno 90 sekund - dość,
#: żeby zdążyć, i za mało, żeby podejrzany kod był użyteczny długo.
TOLERANCJA_KROKOW = 1


def nowy_sekret() -> str:
    """
    Nowy sekret w base32, w postaci, jakiej oczekują aplikacje uwierzytelniające.

    160 bitów, czyli tyle, ile wynosi rozmiar bloku HMAC-SHA1 - dłuższy nic
    nie dodaje, krótszy niepotrzebnie zawęża.
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _sekret_na_bajty(sekret: str) -> bytes:
    """Base32 z powrotem na bajty, z uzupełnieniem wyrównania."""
    czysty = sekret.strip().replace(" ", "").upper()
    uzupelnienie = "=" * (-len(czysty) % 8)
    return base64.b32decode(czysty + uzupelnienie)


def kod(sekret: str, chwila: float | None = None, cyfr: int = CYFR) -> str:
    """
    Kod dla podanej chwili. Bez argumentu - dla teraz.

    Implementacja wprost z RFC 6238: numer kroku czasowego jako osiem bajtów
    big-endian, HMAC-SHA1, a potem ścięcie dynamiczne - cztery ostatnie bity
    skrótu wskazują, skąd wziąć cztery bajty wyniku.
    """
    if chwila is None:
        chwila = time.time()

    licznik = int(chwila) // KROK_SEKUND
    skrot = hmac.new(_sekret_na_bajty(sekret), struct.pack(">Q", licznik), hashlib.sha1).digest()

    przesuniecie = skrot[-1] & 0x0F
    wycinek = struct.unpack(">I", skrot[przesuniecie : przesuniecie + 4])[0] & 0x7FFFFFFF

    return str(wycinek % (10**cyfr)).zfill(cyfr)


def zweryfikuj(sekret: str, podany: str, chwila: float | None = None) -> int | None:
    """
    Sprawdza kod i zwraca numer kroku czasowego, w którym pasował.

    Zwraca numer kroku, a nie True, celowo: wywołujący musi go zapamiętać,
    żeby odrzucić ponowne użycie tego samego kodu. Bez tego kod podejrzany
    przez ramię albo przechwycony na fałszywej stronie logowania działa przez
    całe swoje okno - a to wystarcza, żeby ktoś zdążył go użyć.

    `None` oznacza kod niepasujący.
    """
    if chwila is None:
        chwila = time.time()

    podany = (podany or "").strip().replace(" ", "")
    if not podany.isdigit():
        return None

    for przesuniecie in range(-TOLERANCJA_KROKOW, TOLERANCJA_KROKOW + 1):
        moment = chwila + przesuniecie * KROK_SEKUND
        # compare_digest, nie ==: porównanie napisów kończy się na pierwszej
        # różnicy, więc czas odpowiedzi zdradza, ile początkowych cyfr było
        # trafionych. Przy sześciu cyfrach to skraca zgadywanie z miliona prób
        # do kilkudziesięciu.
        if hmac.compare_digest(kod(sekret, moment), podany):
            return int(moment) // KROK_SEKUND

    return None


def adres_do_aplikacji(sekret: str, login: str, wydawca: str) -> str:
    """
    Adres `otpauth://`, z którego powstaje kod QR.

    Kod QR rysuje przeglądarka - obrazek generowany po stronie serwera
    znaczyłby, że sekret przechodzi przez jeszcze jedno miejsce i ląduje
    w pamięci podręcznej pośredników.
    """
    etykieta = quote(f"{wydawca}:{login}", safe="")
    return (
        f"otpauth://totp/{etykieta}"
        f"?secret={sekret}"
        f"&issuer={quote(wydawca, safe='')}"
        f"&algorithm=SHA1&digits={CYFR}&period={KROK_SEKUND}"
    )
