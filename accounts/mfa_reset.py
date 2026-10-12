"""
Wyłączenie drugiego składnika osobie, która straciła telefon i kody zapasowe.

Jedna droga dla obu, którzy to robią: obsługi (polecenie `wylacz_mfa`, po
weryfikacji z docs/utrata-mfa.md) i właściciela firmy (Zespół w panelu, od
2.32.0). Wcześniej logika żyła tylko w poleceniu; druga kopia w widoku
rozjechałaby się przy pierwszej poprawce - na przykład jedna z nich
przestałaby kończyć sesje, a przejęta sesja przetrwałaby wyłączenie ochrony.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from accounts.models import DrugiSkladnik, KodZapasowy
from accounts.sessions import LoginSession

TEMAT_WYLACZENIA = "Drugi składnik logowania na Twoim koncie został wyłączony"


def wylacz_drugi_skladnik(uzytkownik, teraz=None) -> int:
    """
    Usuwa składnik i kody zapasowe, kończy wszystkie sesje osoby.

    Wywołujący trzyma transakcję i blokadę wiersza osoby. Zwraca liczbę
    zakończonych sesji. Wpis w dzienniku robi wywołujący: z panelu zapisuje
    go middleware, z polecenia - samo polecenie.
    """
    teraz = teraz or timezone.now()
    KodZapasowy.objects.filter(uzytkownik=uzytkownik).delete()
    DrugiSkladnik.objects.filter(uzytkownik=uzytkownik).delete()
    return LoginSession.objects.filter(user=uzytkownik, revoked_at__isnull=True).update(
        revoked_at=teraz
    )


def tresc_ostrzezenia(uzytkownik, kiedy, kto: str) -> str:
    return (
        f"Dzień dobry,\n\n"
        f"{timezone.localtime(kiedy):%d.%m.%Y o %H:%M} {kto} wyłączył(a) drugi składnik "
        f"logowania (kod z aplikacji) na koncie {uzytkownik.email}. Wszystkie sesje "
        f"logowania na tym koncie zostały zakończone.\n\n"
        f"Po zalogowaniu włącz drugi składnik ponownie (Ustawienia konta -> bezpieczeństwo) "
        f"i zapisz nowe kody zapasowe w bezpiecznym miejscu.\n\n"
        f"JEŚLI TO NIE TY prosiłeś o wyłączenie: od razu zmień hasło przez „Nie pamiętam hasła” "
        f"i odpowiedz na tę wiadomość. Ktoś mógł podszyć się pod Ciebie.\n"
    )


def wyslij_ostrzezenie(uzytkownik, kiedy, kto: str) -> None:
    """Mail do osoby, której wyłączono ochronę. Rzuca wyjątek, gdy nie wyszedł."""
    if not send_mail(
        subject=TEMAT_WYLACZENIA,
        message=tresc_ostrzezenia(uzytkownik, kiedy, kto),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[uzytkownik.email],
        fail_silently=False,
    ):
        raise RuntimeError("send_mail zwrócił 0")
