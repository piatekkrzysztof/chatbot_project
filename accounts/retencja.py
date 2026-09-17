"""
Okresy przechowywania i jedno miejsce, które mówi, co jest do usunięcia.

Okresy zatwierdzone przez właściciela 17.09.2026, na liczbach z pierwszego
raportu na produkcji ([docs/przeplywy-danych.md](../docs/przeplywy-danych.md)).

Dlaczego reguły stoją w jednym module, a nie w każdej komendzie z osobna:
raport i usuwanie muszą odpowiadać tym samym warunkiem. Dwie kopie tej samej
reguły rozjeżdżają się po cichu, a wtedy raport obiecuje jedno, a nocne zadanie
robi drugie - i nikt tego nie zauważy, bo obie liczby wyglądają wiarygodnie.
Ten rozjazd nie jest teoretyczny: pierwszy raport z produkcji pokazał
zaproszenie sprzed jednego dnia jako „bezużyteczne od ponad 90 dni", bo warunek
wieku był napisany osobno dla każdej gałęzi.

Czego tu nie ma: rozmów odwiedzających. Mają własny okres, ustawiany przez
każdego klienta w panelu (`data_retention_days`), i własne zadanie od dawna
działające w harmonogramie.
"""

from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from accounts.models import InvitationToken, MfaChallenge, PendingRegistration, WpisDziennika
from accounts.security_notifications import PasswordNotification
from accounts.sessions import LoginSession

# Ile trzymamy. Zmiana którejkolwiek wartości zmienia zachowanie nocnego
# zadania, więc jest decyzją właściciela, nie porządkami w kodzie.
OKRESY = {
    # Rok: krócej nie odpowiemy na pytanie o zdarzenie sprzed roku, dłużej
    # trudno uzasadnić przechowywanie adresów IP i nazw kont przy audycie
    # ochrony danych. To kompromis między dowodem a minimalizacją, nie
    # oszczędność miejsca - dziennik rośnie o kilka wpisów dziennie.
    "dziennik": timedelta(days=365),
    # Liczone od utworzenia, bo moment przyjęcia zaproszenia nie jest nigdzie
    # zapisany. Trzydzieści dni wystarczy, żeby w panelu zobaczyć, kogo się
    # zapraszało; dłużej trzymalibyśmy adres osoby, która konta nie założyła.
    "zaproszenia": timedelta(days=30),
    # Doba zapasu po wygaśnięciu: wygasła sesja nie daje już dostępu, a zapas
    # zostawia ślad na czas ewentualnego pytania „dlaczego mnie wylogowało".
    "sesje": timedelta(days=1),
    "wyzwania_mfa": timedelta(days=1),
    # Tyle, ile miał czas na dokończenie rejestracji.
    "rejestracje": timedelta(days=7),
    # Wysłane i nieudane. Nieudane warto móc obejrzeć, zanim znikną - to jedyny
    # ślad po powiadomieniu, które nie doszło.
    "powiadomienia": timedelta(days=90),
}

NAZWY = {
    "dziennik": "Dziennik audytowy",
    "zaproszenia": "Zaproszenia do zespołu",
    "sesje": "Sesje logowania",
    "wyzwania_mfa": "Wyzwania drugiego składnika",
    "rejestracje": "Rozpoczęte rejestracje",
    "powiadomienia": "Kolejka powiadomień o zmianie hasła",
}


def zaproszenia_nie_do_uzycia(teraz):
    """
    Zaproszenia, których nikt już nie użyje: wygasłe albo wykorzystane do końca.

    Termin ważności nie jest polem w bazie, tylko sumą `created_at` i długości
    wybranej przy tworzeniu - stąd warunek budowany osobno dla każdej długości.
    Filtr po stronie bazy, a nie pętla w Pythonie: ma działać także wtedy, gdy
    zaproszeń będą tysiące.
    """
    warunek = Q(users__gte=F("max_users"))
    for wybor, delta in InvitationToken.DURATION_DELTAS.items():
        warunek |= Q(duration=wybor, created_at__lt=teraz - delta)
    return InvitationToken.objects.filter(warunek)


def _dziennik(teraz):
    return WpisDziennika.objects.filter(czas__lt=teraz - OKRESY["dziennik"])


def _zaproszenia(teraz):
    # Wiek liczony od utworzenia: kiedy ktoś przyjął zaproszenie, baza nie wie.
    return zaproszenia_nie_do_uzycia(teraz).filter(created_at__lt=teraz - OKRESY["zaproszenia"])


def _sesje(teraz):
    return LoginSession.objects.filter(expires_at__lt=teraz - OKRESY["sesje"])


def _wyzwania_mfa(teraz):
    return MfaChallenge.objects.filter(expires_at__lt=teraz - OKRESY["wyzwania_mfa"])


def _rejestracje(teraz):
    return PendingRegistration.objects.filter(created_at__lt=teraz - OKRESY["rejestracje"])


def _powiadomienia(teraz):
    return PasswordNotification.objects.filter(
        status__in=[PasswordNotification.Status.SENT, PasswordNotification.Status.FAILED],
        created_at__lt=teraz - OKRESY["powiadomienia"],
    )


REGULY = {
    "dziennik": _dziennik,
    "zaproszenia": _zaproszenia,
    "sesje": _sesje,
    "wyzwania_mfa": _wyzwania_mfa,
    "rejestracje": _rejestracje,
    "powiadomienia": _powiadomienia,
}


def do_usuniecia(klucz, teraz=None):
    """Wiersze objęte regułą w podanej chwili. Niczego nie usuwa."""
    return REGULY[klucz](teraz or timezone.now())


def usun(klucz, *, teraz=None, proba=False, partia=1000):
    """
    Usuwa wiersze objęte regułą i zwraca, ile ich było.

    Partiami, bo jedno `DELETE` na sto tysięcy wierszy blokuje tabelę na czas,
    którego nikt nie przewidział, a przerwane w połowie zostawia transakcję do
    wycofania. Przy partiach przerwany przebieg zostawia bazę w stanie
    pośrednim, ale spójnym - następny przebieg dokończy resztę.

    Chwila jest ustalana raz i przekazywana dalej: gdyby każda partia liczyła
    „teraz" od nowa, granica przesuwałaby się w trakcie przebiegu.

    Liczymy wiersze tego modelu, a nie sumę z `delete()`, bo ta obejmuje też
    kaskady - przy dzienniku i sesjach to dziś to samo, ale nie musi zostać.
    """
    teraz = teraz or timezone.now()
    wiersze = do_usuniecia(klucz, teraz)
    if proba:
        return wiersze.count()
    model = wiersze.model
    usuniete = 0
    while klucze := list(wiersze.values_list("pk", flat=True)[:partia]):
        model.objects.filter(pk__in=klucze).delete()
        usuniete += len(klucze)
    return usuniete


def usun_wszystko(*, teraz=None, proba=False, partia=1000):
    """Wszystkie reguły naraz; zwraca słownik klucz → ile wierszy."""
    teraz = teraz or timezone.now()
    return {klucz: usun(klucz, teraz=teraz, proba=proba, partia=partia) for klucz in REGULY}
