"""
Autor wpisu dziennika audytowego tam, gdzie middleware sam go nie zna.

Dziennik bierze osobę z `request.user`. Logowanie, drugi krok, wylogowanie,
potwierdzenie rejestracji, przyjęcie zaproszenia i nowe hasło z linku dzieją
się jednak bez zalogowanego użytkownika - osobę poznaje dopiero widok, po
sprawdzeniu hasła, kodu albo tokenu. Wpis powstawał wtedy bez osoby i bez
firmy, więc właściciel nie widział w swoim dzienniku ani jednego logowania.

Widok wskazuje autora dopiero PO udanym sprawdzeniu. Nieudana próba zostaje
anonimowa celowo: przypisanie jej do konta pozwalałoby każdemu dopisywać
wpisy do dziennika cudzej firmy, znając sam login.
"""

ATRYBUT_AUTORA = "_autor_dziennika"


def wskaz_autora(zadanie, uzytkownik):
    """Zapamiętuje osobę na żądaniu Django, także gdy dostaje żądanie DRF."""
    if uzytkownik is not None:
        setattr(getattr(zadanie, "_request", zadanie), ATRYBUT_AUTORA, uzytkownik)


def wskazany_autor(zadanie):
    return getattr(zadanie, ATRYBUT_AUTORA, None)
