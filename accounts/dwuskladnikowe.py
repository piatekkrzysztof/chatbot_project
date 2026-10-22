"""
Logika drugiego składnika: kody zapasowe, weryfikacja, bilet między krokami.

Trzymana osobno od widoków, bo te same reguły obowiązują w dwóch miejscach -
przy potwierdzaniu konfiguracji i przy logowaniu - a rozjechanie się ich
znaczyłoby, że jedna droga sprawdza mniej niż druga.
"""

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from accounts import totp

#: Ile kodów zapasowych wydajemy przy włączaniu drugiego składnika.
ILE_KODOW_ZAPASOWYCH = 10

#: Ważność biletu między pierwszym a drugim krokiem logowania.
#:
#: Pięć minut: tyle wystarcza, żeby sięgnąć po telefon i przepisać kod, a za
#: mało, żeby bilet przechwycony z logów albo z historii przeglądarki był
#: jeszcze do czegoś przydatny.
WAZNOSC_BILETU_SEKUND = 300

_SOL_BILETU = "logowanie-drugi-skladnik"

#: Ile błędnych kodów drugiego kroku na konto w ciągu doby, zanim drugi krok
#: się zamknie. Do 2.32.13 jedyną granicą było 10 prób na 5 minut, bez końca:
#: kto znał hasło, miał ok. 0,9% szans dziennie na trafienie kodu, a osoba,
#: której hasło wyciekło, nie dowiadywała się o niczym (audyt 2026-10, P16).
#: Dwadzieścia to kilka pomyłek dziennie z dużym zapasem - człowiek, który
#: przepisuje kod z telefonu, nie myli się dwadzieścia razy.
DOBOWY_LIMIT_BLEDNYCH_KODOW = 20
OKNO_DOBOWE_SEKUND = 24 * 3600


def skrot_kodu(kod: str) -> str:
    """Skrót kodu zapasowego. Znormalizowany, żeby spacje i wielkość liter nie miały znaczenia."""
    czysty = (kod or "").strip().replace(" ", "").replace("-", "").upper()
    return hashlib.sha256(czysty.encode("utf-8")).hexdigest()


@transaction.atomic
def wygeneruj_kody_zapasowe(uzytkownik) -> list[str]:
    """
    Wydaje nowy komplet kodów zapasowych, kasując poprzedni.

    Zwraca kody OTWARTYM TEKSTEM - jedyny raz, kiedy istnieją poza głową
    użytkownika. W bazie lądują wyłącznie skróty, więc odtworzenie ich później
    jest niemożliwe i tak ma być: lista możliwa do odczytania po fakcie jest
    listą, którą da się wykraść.
    """
    from accounts.models import CustomUser, KodZapasowy

    CustomUser.objects.select_for_update().get(pk=uzytkownik.pk)
    KodZapasowy.objects.filter(uzytkownik=uzytkownik).delete()

    kody = []
    for _ in range(ILE_KODOW_ZAPASOWYCH):
        # Cztery bajty na człon, dwa człony - dość entropii, żeby nie dało się
        # zgadywać, i na tyle krótko, żeby dało się przepisać z kartki.
        kod = f"{secrets.token_hex(4)}-{secrets.token_hex(4)}".upper()
        kody.append(kod)
        KodZapasowy.objects.create(uzytkownik=uzytkownik, skrot=skrot_kodu(kod))

    return kody


def zuzyj_kod_zapasowy(uzytkownik, podany: str) -> bool:
    """
    Sprawdza kod zapasowy i oznacza go jako zużyty.

    Zapytanie po skrócie, nie po tekście: baza nigdy nie widzi kodu, a
    porównanie po indeksie jest stałe względem liczby kodów.
    """
    from accounts.models import KodZapasowy

    return (
        KodZapasowy.objects.filter(
            uzytkownik=uzytkownik, skrot=skrot_kodu(podany), uzyty__isnull=True
        ).update(uzyty=timezone.now())
        == 1
    )


@transaction.atomic
def sprawdz_kod(skladnik, podany: str) -> bool:
    """
    Sprawdza kod z aplikacji i zamyka drogę do jego ponownego użycia.

    Numer kroku zapisujemy PRZED zwróceniem prawdy, więc ten sam kod przestaje
    działać natychmiast po pierwszym udanym użyciu. Bez tego kod podejrzany
    przez ramię jest ważny jeszcze przez resztę swojego okna - a to wystarcza,
    żeby ktoś zdążył go użyć.
    """
    from accounts.models import DrugiSkladnik

    current = DrugiSkladnik.objects.select_for_update().filter(pk=skladnik.pk).first()
    if current is None:
        return False
    krok = totp.zweryfikuj(current.sekret, podany)
    if krok is None:
        return False

    if current.ostatni_krok is not None and krok <= current.ostatni_krok:
        return False

    current.ostatni_krok = skladnik.ostatni_krok = krok
    current.save(update_fields=["ostatni_krok"])
    return True


def ma_wlaczony_drugi_skladnik(uzytkownik) -> bool:
    from accounts.models import DrugiSkladnik

    return DrugiSkladnik.objects.filter(
        uzytkownik=uzytkownik,
        potwierdzony_od__isnull=False,
    ).exists()


def fingerprint(user, factor):
    value = f"{user.password}:{factor.pk}:{factor.sekret}:{factor.potwierdzony_od.isoformat()}"
    return salted_hmac("mfa-state", value, algorithm="sha256").hexdigest()


def wystaw_bilet(uzytkownik) -> str:
    """
    Bilet potwierdzający, że hasło już zostało sprawdzone.

    Podpisany identyfikator losowego wyzwania w bazie; jednorazowy i związany
    ze stanem hasła oraz drugiego składnika.
    """
    from accounts.models import DrugiSkladnik, MfaChallenge

    factor = DrugiSkladnik.objects.get(uzytkownik=uzytkownik, potwierdzony_od__isnull=False)
    challenge = MfaChallenge.objects.create(
        user=uzytkownik,
        fingerprint=fingerprint(uzytkownik, factor),
        expires_at=timezone.now() + timedelta(seconds=WAZNOSC_BILETU_SEKUND),
    )
    return signing.dumps({"id": str(challenge.pk)}, salt=_SOL_BILETU)


def challenge_id(bilet):
    if not isinstance(bilet, str) or len(bilet) > 1024:
        return None
    try:
        data = signing.loads(bilet, salt=_SOL_BILETU, max_age=WAZNOSC_BILETU_SEKUND)
        return UUID(data["id"])
    except (signing.BadSignature, ValueError, TypeError, KeyError, AttributeError):
        return None


def valid_challenge(challenge, user, factor):
    return bool(
        challenge
        and user.is_active
        and factor
        and factor.wlaczony
        and challenge.used_at is None
        and challenge.failures < 5
        and challenge.expires_at > timezone.now()
        and constant_time_compare(challenge.fingerprint, fingerprint(user, factor))
    )


def _klucz_dobowy(uzytkownik):
    # Z odciskiem hasła: zmiana hasła - to radzi ostrzeżenie - zaczyna licznik
    # od nowa, więc właściciel konta odblokowuje się sam, bez obsługi.
    odcisk = salted_hmac("mfa-dobowy-limit", f"{uzytkownik.pk}:{uzytkownik.password}").hexdigest()
    return f"mfa-doba:{odcisk}"


def drugi_krok_zamkniety(uzytkownik) -> bool:
    """Czy konto wyczerpało dobowy limit błędnych kodów przy obecnym haśle."""
    from api.mfa_throttles import MfaUnavailable

    try:
        return (cache.get(_klucz_dobowy(uzytkownik)) or 0) >= DOBOWY_LIMIT_BLEDNYCH_KODOW
    except Exception:
        # Bez licznika nie wiemy, czy limit nie minął - drugi krok zamknięty,
        # jak przy każdym innym limicie MFA.
        raise MfaUnavailable() from None


def zapisz_bledny_kod(uzytkownik):
    """Liczy błędny kod; przy osiągnięciu limitu zleca jedno ostrzeżenie."""
    from api.mfa_throttles import MfaUnavailable

    klucz = _klucz_dobowy(uzytkownik)
    try:
        ile = 1 if cache.add(klucz, 1, timeout=OKNO_DOBOWE_SEKUND) else cache.incr(klucz)
    except Exception:
        raise MfaUnavailable() from None
    if ile == DOBOWY_LIMIT_BLEDNYCH_KODOW:
        from accounts.tasks import ostrzez_o_blednych_kodach
        from documents.utils.queue import enqueue

        identyfikator = uzytkownik.pk
        transaction.on_commit(lambda: enqueue(ostrzez_o_blednych_kodach, identyfikator))


TEMAT_OSTRZEZENIA = "Ktoś zna hasło do Twojego konta"


def tresc_ostrzezenia(uzytkownik) -> str:
    return (
        "Dzień dobry,\n\n"
        f"ktoś podał poprawne hasło do konta {uzytkownik.email}, ale "
        f"{DOBOWY_LIMIT_BLEDNYCH_KODOW} razy błędny kod z aplikacji uwierzytelniającej. "
        "Żeby nie mógł zgadywać dalej, logowanie na to konto jest wstrzymane na dobę.\n\n"
        "JEŚLI TO NIE TY: od razu zmień hasło przez „Nie pamiętam hasła”. Zmiana hasła "
        "zdejmuje też blokadę logowania.\n\n"
        "Jeśli to Ty - sprawdź, czy zegar telefonu jest ustawiony automatycznie, i zaloguj "
        "się kodem zapasowym albo po zmianie hasła.\n"
    )


def wyslij_ostrzezenie_o_kodach(uzytkownik) -> None:
    """Mail do osoby, na której koncie zamknął się drugi krok. Rzuca, gdy nie wyszedł."""
    if not send_mail(
        subject=TEMAT_OSTRZEZENIA,
        message=tresc_ostrzezenia(uzytkownik),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[uzytkownik.email],
        fail_silently=False,
    ):
        raise RuntimeError("send_mail zwrócił 0")


@transaction.atomic
def zakoncz_logowanie(bilet, kod):
    from accounts.models import CustomUser, DrugiSkladnik, MfaChallenge
    from api.mfa_throttles import account_attempt

    identity = challenge_id(bilet)
    if identity is None:
        return None, 401
    preliminary = MfaChallenge.objects.filter(pk=identity).first()
    if preliminary is None:
        return None, 401
    # Account security mutations lock user before factor and challenge.
    user = CustomUser.objects.select_for_update().filter(pk=preliminary.user_id).first()
    if user is None:
        return None, 401
    factor = DrugiSkladnik.objects.select_for_update().filter(uzytkownik=user).first()
    challenge = MfaChallenge.objects.select_for_update().filter(pk=identity).first()
    if not valid_challenge(challenge, user, factor):
        return None, 401
    account_attempt(user)
    if drugi_krok_zamkniety(user):
        # Także dla poprawnego kodu - inaczej blokada nie zatrzymałaby zgadywania.
        return None, 429
    if not (sprawdz_kod(factor, kod) or zuzyj_kod_zapasowy(user, kod)):
        challenge.failures += 1
        challenge.save(update_fields=["failures"])
        zapisz_bledny_kod(user)
        return None, 400
    challenge.used_at = timezone.now()
    challenge.save(update_fields=["used_at"])
    return user, 200


def nazwa_wydawcy() -> str:
    """Nazwa, pod którą wpis pojawi się w aplikacji uwierzytelniającej."""
    return getattr(settings, "NAZWA_PRODUKTU", "SM-art Chat")
