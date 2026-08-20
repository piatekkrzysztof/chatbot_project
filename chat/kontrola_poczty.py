"""
Kontrola konfiguracji poczty — wyłapuje błędne wartości, nie tylko brakujące.

Wcześniejsza wersja tego sprawdzenia (w settings/base.py) pytała wyłącznie
o OBECNOŚĆ zmiennych. Obie awarie, które realnie wystąpiły na produkcji,
przeszły przez nie bez słowa, bo wartości były obecne — tylko błędne:

  • EMAIL_HOST = "stmp.resend.com" na usłudze web (przestawione litery),
  • DEFAULT_FROM_EMAIL = "powiadomienia@agencjasm_art.pl" na workerze
    (podkreślnik zamiast myślnika).

Obie ujawniły się dopiero przy próbie wysłania prawdziwego powiadomienia
o zapytaniu od klienta — czyli w najgorszym możliwym momencie. Obie były
wklepane ręcznie w panelu Rendera, osobno na każdej usłudze, więc nic ich
ze sobą nie porównywało.

Sprawdzenie jest CZYSTE — nie rusza sieci. Zwraca listę problemów, decyzję
co z nimi zrobić zostawia wywołującemu. Dzięki temu da się je przetestować
bez stawiania serwera poczty i bez czekania na DNS przy starcie procesu.
"""
from email.utils import parseaddr

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

# Znak, którego nie ma w poprawnej nazwie hosta, a który łatwo wkleić razem
# z adresem strony ("https://smtp.resend.com/" zamiast samej nazwy).
ZNAKI_NIEDOZWOLONE_W_HOSCIE = ("/", " ", "\t", "@", ":")


def problemy_z_konfiguracja(ustawienia):
    """
    Lista czytelnych opisów problemów. Pusta = konfiguracja wygląda poprawnie.

    „Wygląda" jest tu dosłowne: sprawdzamy kształt wartości, nie to, czy
    serwer istnieje i przyjmie logowanie. Literówki typu "stmp" są poprawnym
    kształtem nazwy hosta i wychodzą dopiero przy próbie połączenia — od tego
    jest komenda `sprawdz_poczte`.
    """
    if not ustawienia.EMAIL_BACKEND.endswith("smtp.EmailBackend"):
        # Backend konsolowy albo pamięciowy — nic nie wychodzi na zewnątrz,
        # więc adres nadawcy i host nie mają znaczenia.
        return []

    problemy = []

    if not ustawienia.EMAIL_HOST_PASSWORD:
        problemy.append(
            "EMAIL_HOST_PASSWORD jest puste — w Resendzie hasłem jest klucz API."
        )

    host = (ustawienia.EMAIL_HOST or "").strip()
    if not host:
        problemy.append("EMAIL_HOST jest puste.")
    else:
        if any(znak in host for znak in ZNAKI_NIEDOZWOLONE_W_HOSCIE):
            problemy.append(
                f"EMAIL_HOST = {host!r} to nie jest sama nazwa hosta "
                "(oczekiwane np. 'smtp.resend.com', bez schematu i ukośników)."
            )
        elif "." not in host:
            problemy.append(
                f"EMAIL_HOST = {host!r} nie wygląda na pełną nazwę domenową."
            )

    nadawca = ustawienia.DEFAULT_FROM_EMAIL or ""
    if not nadawca:
        problemy.append(
            "DEFAULT_FROM_EMAIL jest puste — nadawca to osobna rzecz niż login SMTP."
        )
    else:
        # Dopuszczamy formę 'Nazwa <adres@domena>' — sam validate_email ją
        # odrzuca, a to poprawna i częsta wartość tej zmiennej.
        _, adres = parseaddr(nadawca)
        try:
            validate_email(adres)
        except ValidationError:
            problemy.append(
                f"DEFAULT_FROM_EMAIL = {nadawca!r} nie jest poprawnym adresem "
                "(serwer odrzuci wysyłkę z błędem 501)."
            )

    return problemy
