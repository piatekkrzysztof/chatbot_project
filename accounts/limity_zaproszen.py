"""
Dzienne pułapy zaproszeń (przegląd 2026-11, R07).

Zaproszenie to mail z naszej domeny z nazwą firmy, którą wpisał nadawca. Do
2.32.23 nic nie ograniczało, ile ich wyjdzie: właściciel mógł wystawiać je bez
końca (cofnięcie kasuje wiersz, więc baza nie pamiętała nawet, ile ich było),
a publiczny link „wyślij ponownie" wysyłał co minutę, przez cały tydzień
ważności zaproszenia. Wystarczyło konto w okresie próbnym, żeby zamienić naszą
pocztę w źródło spamu albo phishingu podpisanego dowolną nazwą firmy - i
zepsuć reputację domeny, z której idą maile wszystkich klientów.

Liczniki są we wspólnej pamięci podręcznej, nie w bazie, właśnie dlatego, że
cofnięte zaproszenie znika z bazy. Gdy pamięć podręczna nie działa, odmawiamy
(503) - jak przy rejestracji: niedostępny licznik nie może znaczyć „bez limitu".
"""

import time

from django.conf import settings
from django.core.cache import cache
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import APIException, Throttled

from accounts.registration import normalized_email

DOBA_S = 24 * 3600


class ZaproszeniaNiedostepne(APIException):
    status_code = 503
    default_detail = "Wysyłka zaproszeń jest chwilowo niedostępna. Spróbuj za chwilę."
    default_code = "zaproszenia_niedostepne"


def _policz(klucz):
    """Zwiększa licznik bieżącej doby i zwraca jego nową wartość."""
    teraz = time.time()
    pelny = f"zaproszenia:{klucz}:{int(teraz // DOBA_S)}"
    try:
        if cache.add(pelny, 1, timeout=DOBA_S + 1):
            return 1, teraz
        return cache.incr(pelny), teraz
    except Exception:
        raise ZaproszeniaNiedostepne() from None


def _do_konca_doby(teraz):
    return max(1, int(DOBA_S - teraz % DOBA_S))


def sprawdz_wystawienie(tenant, email):
    """
    Liczy wystawienie zaproszenia; Throttled (429), gdy firma przekroczyła pułap.

    Dwa liczniki: ile zaproszeń firma wystawiła dziś w ogóle i ile na ten
    jeden adres. Adres w kluczu jako skrót - pamięć podręczna to nie miejsce
    na listę cudzych skrzynek.
    """
    adres = salted_hmac("zaproszenia-adres", normalized_email(email)).hexdigest()
    for klucz, limit, komunikat in (
        (
            f"adres:{tenant.pk}:{adres}",
            settings.LIMIT_ZAPROSZEN_NA_ADRES_DZIENNIE,
            "Na ten adres wystawiono dziś już kilka zaproszeń. Skopiuj link z listy "
            "zaproszeń albo spróbuj jutro.",
        ),
        (
            f"firma:{tenant.pk}",
            settings.LIMIT_ZAPROSZEN_FIRMY_DZIENNIE,
            "Dzienny limit zaproszeń został wykorzystany. Spróbuj jutro.",
        ),
    ):
        licznik, teraz = _policz(klucz)
        if licznik > limit:
            raise Throttled(wait=_do_konca_doby(teraz), detail=komunikat)


def wysylka_ponowna_dozwolona(zaproszenie):
    """
    Czy publiczny link może dziś jeszcze raz wysłać to zaproszenie.

    Odstęp minuty między wysyłkami pilnuje sam widok; ten pułap zamyka to, czego
    odstęp nie zamyka - 1440 maili na dobę do jednej skrzynki.
    """
    licznik, _ = _policz(f"ponowna:{zaproszenie.pk}")
    return licznik <= settings.LIMIT_WYSYLEK_ZAPROSZENIA_DZIENNIE
