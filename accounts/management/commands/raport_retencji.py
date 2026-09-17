"""
Ile danych zniknęłoby przy każdym progu. Raport - niczego nie usuwa.

Okresy przechowywania są decyzją właściciela, ale decyzja podjęta bez liczb
jest zgadywaniem: „dwanaście miesięcy" brzmi rozsądnie, dopóki nie okaże się,
że dotyczy trzech wpisów albo trzystu tysięcy. Ten raport pokazuje, co który
próg naprawdę zabiera, zanim cokolwiek zostanie włączone.

Zasady, które trzymają ten raport przy prawdzie:

* **Nic nie kasuje i nie zmienia.** Odbiór F21 jest zamknięty, ale włączenie
  automatycznego usuwania to osobna decyzja i osobna zmiana.
* **Liczy tym samym warunkiem, co komenda, która potem usuwa.** Raport
  obiecujący inne liczby niż wykonanie byłby gorszy od braku raportu, bo
  decyzja zapadłaby na podstawie fikcji. Pilnuje tego test porównujący raport
  z rzeczywistym przebiegiem istniejących komend.
* **Wiersze nietykalne są wypisane osobno**, a nie pominięte po cichu:
  ważne zaproszenie i niewysłane powiadomienie nie znikają przy żadnym progu,
  bo ich usunięcie odebrałoby komuś dostęp albo zgubiło wiadomość.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import F, Min, Q
from django.utils import timezone

from accounts.models import InvitationToken, MfaChallenge, PendingRegistration, WpisDziennika
from accounts.security_notifications import PasswordNotification
from accounts.sessions import LoginSession

MIESIAC = timedelta(days=30)


def raport_dziennika(teraz):
    """Dziennik audytowy: jedyna odpowiedź na pytanie „kto to zrobił"."""
    wiersze = WpisDziennika.objects.all()
    progi = [
        (f"starsze niż {ile} mies.", wiersze.filter(czas__lt=teraz - ile * MIESIAC).count())
        for ile in (3, 6, 12, 24)
    ]
    return {
        "nazwa": "Dziennik audytowy",
        "model": "accounts.WpisDziennika",
        "reguła": "brak - do ustalenia",
        "wszystkich": wiersze.count(),
        "najstarszy": wiersze.aggregate(x=Min("czas"))["x"],
        "progi": progi,
        "nietykalne": [],
        "uwaga": (
            "Przy sporze z klientem i przy naruszeniu ochrony danych to jedyne źródło "
            "przebiegu zdarzeń. Krótki okres oszczędza miejsce, którego i tak nie brakuje."
        ),
    }


def raport_sesji(teraz):
    wiersze = LoginSession.objects.all()
    return {
        "nazwa": "Sesje logowania",
        "model": "accounts.LoginSession",
        "reguła": "purge_login_sessions: wygasłe od co najmniej 24 h",
        "wszystkich": wiersze.count(),
        "najstarszy": wiersze.aggregate(x=Min("created_at"))["x"],
        "progi": [
            (
                "do usunięcia dziś",
                wiersze.filter(expires_at__lt=teraz - timedelta(days=1)).count(),
            )
        ],
        "nietykalne": [("ważne sesje", wiersze.filter(expires_at__gte=teraz).count())],
        "uwaga": "Komenda gotowa od dawna, brakowało tylko harmonogramu.",
    }


def raport_wyzwan_mfa(teraz):
    wiersze = MfaChallenge.objects.all()
    return {
        "nazwa": "Wyzwania drugiego składnika",
        "model": "accounts.MfaChallenge",
        "reguła": "purge_mfa_challenges: wygasłe od co najmniej 24 h",
        "wszystkich": wiersze.count(),
        "najstarszy": None,
        "progi": [
            (
                "do usunięcia dziś",
                wiersze.filter(expires_at__lt=teraz - timedelta(days=1)).count(),
            )
        ],
        "nietykalne": [("ważne wyzwania", wiersze.filter(expires_at__gte=teraz).count())],
        "uwaga": "Krótkożyjące z natury; rosną tylko wtedy, gdy nikt ich nie sprząta.",
    }


def raport_rejestracji(teraz):
    wiersze = PendingRegistration.objects.all()
    return {
        "nazwa": "Rozpoczęte rejestracje",
        "model": "accounts.PendingRegistration",
        "reguła": "purge_pending_registrations: starsze niż 7 dni",
        "wszystkich": wiersze.count(),
        "najstarszy": wiersze.aggregate(x=Min("created_at"))["x"],
        "progi": [
            (
                "do usunięcia dziś",
                wiersze.filter(created_at__lt=teraz - timedelta(days=7)).count(),
            )
        ],
        "nietykalne": [],
        "uwaga": "Zawierają e-mail i dane firmy osoby, która konta nie dokończyła.",
    }


def zaproszenia_nie_do_uzycia(teraz):
    """
    Zaproszenia, których nikt już nie użyje: wygasłe albo wykorzystane do końca.

    Termin ważności nie jest polem w bazie, tylko sumą `created_at` i długości
    wybranej przy tworzeniu - stąd warunek budowany osobno dla każdej długości.
    Filtr po stronie bazy, a nie pętla w Pythonie: raport ma działać także
    wtedy, gdy zaproszeń będą tysiące.
    """
    warunek = Q(users__gte=F("max_users"))
    for wybor, delta in InvitationToken.DURATION_DELTAS.items():
        warunek |= Q(duration=wybor, created_at__lt=teraz - delta)
    return InvitationToken.objects.filter(warunek)


def raport_zaproszen(teraz):
    wiersze = InvitationToken.objects.all()
    bezuzyteczne = zaproszenia_nie_do_uzycia(teraz)
    # Próg liczony od UTWORZENIA, nie od chwili, w której zaproszenie przestało
    # działać. Kiedy ktoś je wykorzystał, w bazie nie ma - jest tylko licznik
    # miejsc. Pierwszy raport z produkcji policzył wykorzystane zaproszenie
    # sprzed jednego dnia jako „bezużyteczne od ponad 90 dni"; liczba brała się
    # stąd, że warunek wykorzystania nie patrzył na wiek w ogóle. Data utworzenia
    # jest tym, co baza wie na pewno - i tym, od czego zwykle liczy się retencję.
    progi = [("nie do użycia już dziś", bezuzyteczne.count())]
    progi += [
        (
            f"j.w. i utworzone ponad {ile} dni temu",
            bezuzyteczne.filter(created_at__lt=teraz - timedelta(days=ile)).count(),
        )
        for ile in (30, 90)
    ]
    nadal_wazne = wiersze.exclude(pk__in=bezuzyteczne.values("pk"))
    return {
        "nazwa": "Zaproszenia do zespołu",
        "model": "accounts.InvitationToken",
        "reguła": "brak - do ustalenia",
        "wszystkich": wiersze.count(),
        "najstarszy": wiersze.aggregate(x=Min("created_at"))["x"],
        "progi": progi,
        "nietykalne": [("ważne i niewykorzystane", nadal_wazne.count())],
        "uwaga": "Niosą adres e-mail osoby, która konta może nigdy nie założyć.",
    }


def raport_powiadomien(teraz):
    wiersze = PasswordNotification.objects.all()
    zamkniete = wiersze.filter(
        status__in=[PasswordNotification.Status.SENT, PasswordNotification.Status.FAILED]
    )
    progi = [
        (
            f"wysłane lub nieudane, starsze niż {ile} dni",
            zamkniete.filter(created_at__lt=teraz - timedelta(days=ile)).count(),
        )
        for ile in (30, 90)
    ]
    w_toku = wiersze.exclude(pk__in=zamkniete.values("pk"))
    return {
        "nazwa": "Kolejka powiadomień o zmianie hasła",
        "model": "accounts.PasswordNotification",
        "reguła": "brak - do ustalenia",
        "wszystkich": wiersze.count(),
        "najstarszy": wiersze.aggregate(x=Min("created_at"))["x"],
        "progi": progi,
        "nietykalne": [("czekające na wysyłkę", w_toku.count())],
        "uwaga": "Niosą adres odbiorcy. Nieudane warto obejrzeć, zanim znikną.",
    }


RAPORTY = [
    raport_dziennika,
    raport_zaproszen,
    raport_sesji,
    raport_wyzwan_mfa,
    raport_rejestracji,
    raport_powiadomien,
]


class Command(BaseCommand):
    help = "Ile danych zniknęłoby przy każdym progu retencji. Niczego nie usuwa."
    requires_system_checks = []

    def handle(self, *args, **options):
        teraz = timezone.now()
        self.stdout.write(
            f"Raport retencji na {teraz:%d.%m.%Y %H:%M} UTC. Nic nie zostało usunięte.\n"
        )

        for zrob_raport in RAPORTY:
            dane = zrob_raport(teraz)
            self.stdout.write(f"\n## {dane['nazwa']} ({dane['model']})")
            self.stdout.write(f"   reguła dziś: {dane['reguła']}")
            self.stdout.write(f"   wierszy: {dane['wszystkich']}")
            if dane["najstarszy"]:
                wiek = (teraz - dane["najstarszy"]).days
                self.stdout.write(f"   najstarszy: {dane['najstarszy']:%d.%m.%Y} ({wiek} dni temu)")
            for opis, ile in dane["progi"]:
                zostanie = dane["wszystkich"] - ile
                self.stdout.write(f"   {opis}: {ile}, zostaje {zostanie}")
            for opis, ile in dane["nietykalne"]:
                self.stdout.write(f"   nie do usunięcia przy żadnym progu - {opis}: {ile}")
            self.stdout.write(f"   {dane['uwaga']}")

        self.stdout.write(
            "\nŻaden próg nie jest włączony. Włączenie usuwania to osobna decyzja "
            "i osobna zmiana w kodzie."
        )
