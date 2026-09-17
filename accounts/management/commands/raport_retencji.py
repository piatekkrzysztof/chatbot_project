"""
Co zniknie przy najbliższym sprzątaniu. Raport - niczego nie usuwa.

Do 17.09.2026 raport pokazywał kilka progów do wyboru, bo okresy nie były
jeszcze ustalone. Są ustalone (`accounts/retencja.py`), więc pytanie zmieniło
się z „ile by zniknęło przy różnych progach" na „ile zniknie dziś w nocy".

Liczy tym samym warunkiem, co nocne zadanie, bo czyta z tego samego modułu.
Raport obiecujący inne liczby niż wykonanie byłby gorszy niż jego brak: decyzja
o danych klientów zapadłaby na podstawie fikcji.
"""

from django.core.management.base import BaseCommand
from django.db.models import Min
from django.utils import timezone

from accounts import retencja
from accounts.models import InvitationToken, MfaChallenge, PendingRegistration, WpisDziennika
from accounts.security_notifications import PasswordNotification
from accounts.sessions import LoginSession

# Pole daty służy wyłącznie do pokazania wieku najstarszego wiersza. Warunki
# usuwania siedzą w regułach i raport nie liczy po tym polu niczego.
POLA_DATY = {
    "dziennik": (WpisDziennika, "czas"),
    "zaproszenia": (InvitationToken, "created_at"),
    "sesje": (LoginSession, "created_at"),
    "wyzwania_mfa": (MfaChallenge, None),
    "rejestracje": (PendingRegistration, "created_at"),
    "powiadomienia": (PasswordNotification, "created_at"),
}

UWAGI = {
    "dziennik": (
        "Przy sporze z klientem i przy naruszeniu ochrony danych to jedyne źródło "
        "przebiegu zdarzeń."
    ),
    "zaproszenia": (
        "Zostają wszystkie ważne i niewykorzystane - ich usunięcie odebrałoby komuś "
        "dostęp do firmy."
    ),
    "sesje": "Zostają sesje ważne; ich usunięcie wylogowałoby ludzi w trakcie pracy.",
    "wyzwania_mfa": "Krótkożyjące z natury; rosną tylko wtedy, gdy nikt ich nie sprząta.",
    "rejestracje": "Zawierają e-mail i dane firmy osoby, która konta nie dokończyła.",
    "powiadomienia": (
        "Zostają czekające na wysyłkę - to jedyny sygnał, jaki dostaje właściciel "
        "przy przejęciu konta."
    ),
}


def opis_okresu(okres):
    dni = okres.days
    if dni % 365 == 0:
        return f"{dni // 365} rok" if dni == 365 else f"{dni // 365} lata"
    if dni % 30 == 0:
        return f"{dni // 30} mies."
    return f"{dni} dni"


class Command(BaseCommand):
    help = "Co zniknie przy najbliższym sprzątaniu retencyjnym. Niczego nie usuwa."
    requires_system_checks = []

    def handle(self, *args, **options):
        teraz = timezone.now()
        self.stdout.write(
            f"Raport retencji na {teraz:%d.%m.%Y %H:%M} UTC. Nic nie zostało usunięte.\n"
        )

        for klucz in retencja.REGULY:
            model, pole = POLA_DATY[klucz]
            wszystkich = model.objects.count()
            do_usuniecia = retencja.do_usuniecia(klucz, teraz).count()

            self.stdout.write(f"\n## {retencja.NAZWY[klucz]} ({model._meta.label})")
            self.stdout.write(f"   okres przechowywania: {opis_okresu(retencja.OKRESY[klucz])}")
            self.stdout.write(f"   wierszy: {wszystkich}")
            if pole and wszystkich:
                najstarszy = model.objects.aggregate(x=Min(pole))["x"]
                if najstarszy:
                    self.stdout.write(
                        f"   najstarszy: {najstarszy:%d.%m.%Y} "
                        f"({(teraz - najstarszy).days} dni temu)"
                    )
            self.stdout.write(
                f"   do usunięcia przy najbliższym przebiegu: {do_usuniecia}, "
                f"zostaje {wszystkich - do_usuniecia}"
            )
            self.stdout.write(f"   {UWAGI[klucz]}")

        self.stdout.write(
            "\nSprzątanie chodzi codziennie o 3:45 UTC na istniejącym workerze. "
            "Ten raport tylko liczy."
        )
