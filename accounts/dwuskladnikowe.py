"""
Logika drugiego składnika: kody zapasowe, weryfikacja, bilet między krokami.

Trzymana osobno od widoków, bo te same reguły obowiązują w dwóch miejscach -
przy potwierdzaniu konfiguracji i przy logowaniu - a rozjechanie się ich
znaczyłoby, że jedna droga sprawdza mniej niż druga.
"""

import hashlib
import secrets

from django.conf import settings
from django.core import signing
from django.utils import timezone

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


def skrot_kodu(kod: str) -> str:
    """Skrót kodu zapasowego. Znormalizowany, żeby spacje i wielkość liter nie miały znaczenia."""
    czysty = (kod or "").strip().replace(" ", "").replace("-", "").upper()
    return hashlib.sha256(czysty.encode("utf-8")).hexdigest()


def wygeneruj_kody_zapasowe(uzytkownik) -> list[str]:
    """
    Wydaje nowy komplet kodów zapasowych, kasując poprzedni.

    Zwraca kody OTWARTYM TEKSTEM - jedyny raz, kiedy istnieją poza głową
    użytkownika. W bazie lądują wyłącznie skróty, więc odtworzenie ich później
    jest niemożliwe i tak ma być: lista możliwa do odczytania po fakcie jest
    listą, którą da się wykraść.
    """
    from accounts.models import KodZapasowy

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

    wpis = KodZapasowy.objects.filter(
        uzytkownik=uzytkownik, skrot=skrot_kodu(podany), uzyty__isnull=True
    ).first()
    if not wpis:
        return False

    wpis.uzyty = timezone.now()
    wpis.save(update_fields=["uzyty"])
    return True


def sprawdz_kod(skladnik, podany: str) -> bool:
    """
    Sprawdza kod z aplikacji i zamyka drogę do jego ponownego użycia.

    Numer kroku zapisujemy PRZED zwróceniem prawdy, więc ten sam kod przestaje
    działać natychmiast po pierwszym udanym użyciu. Bez tego kod podejrzany
    przez ramię jest ważny jeszcze przez resztę swojego okna - a to wystarcza,
    żeby ktoś zdążył go użyć.
    """
    krok = totp.zweryfikuj(skladnik.sekret, podany)
    if krok is None:
        return False

    if skladnik.ostatni_krok is not None and krok <= skladnik.ostatni_krok:
        return False

    skladnik.ostatni_krok = krok
    skladnik.save(update_fields=["ostatni_krok"])
    return True


def ma_wlaczony_drugi_skladnik(uzytkownik) -> bool:
    skladnik = getattr(uzytkownik, "drugi_skladnik", None)
    return bool(skladnik and skladnik.wlaczony)


def wystaw_bilet(uzytkownik) -> str:
    """
    Bilet potwierdzający, że hasło już zostało sprawdzone.

    Podpisany, nie losowy: nie wymaga niczego w bazie ani w pamięci podręcznej,
    a i tak nie da się go podrobić bez klucza aplikacji. Niesie sam identyfikator
    użytkownika - żadnych uprawnień, żadnego dostępu do API.
    """
    return signing.dumps({"uzytkownik": uzytkownik.pk}, salt=_SOL_BILETU)


def odczytaj_bilet(bilet: str):
    """Użytkownik z biletu albo None, gdy bilet jest zły lub przeterminowany."""
    from accounts.models import CustomUser

    try:
        dane = signing.loads(bilet or "", salt=_SOL_BILETU, max_age=WAZNOSC_BILETU_SEKUND)
    except signing.BadSignature:
        return None

    return CustomUser.objects.filter(pk=dane.get("uzytkownik")).first()


def nazwa_wydawcy() -> str:
    """Nazwa, pod którą wpis pojawi się w aplikacji uwierzytelniającej."""
    return getattr(settings, "NAZWA_PRODUKTU", "SM-art Chat")
