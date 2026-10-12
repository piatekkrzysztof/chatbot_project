"""
Wyłączenie drugiego składnika osobie, która straciła telefon i kody zapasowe.

Procedura i weryfikacja tożsamości: docs/utrata-mfa.md. To polecenie jest
jej ostatnim krokiem - uruchamia je operator (Render -> Shell) dopiero PO
potwierdzeniu, że prosi właściciel konta.

Dwa kroki z dobą przerwy (decyzja właściciela z 11.10.2026):

    python manage.py wylacz_mfa --email osoba@firma.pl --zgloszenie "opis weryfikacji"
    python manage.py wylacz_mfa --email osoba@firma.pl --zgloszenie "..." --zapowiedz
    # najwcześniej 24 h później:
    python manage.py wylacz_mfa --email osoba@firma.pl --zgloszenie "..." --wykonaj

Bez opcji tylko pokazuje, czego dotyczy. `--zapowiedz` wysyła na adres konta
„otrzymaliśmy prośbę o wyłączenie - jeśli to nie Ty, odpowiedz” i zapisuje
wpis w dzienniku firmy. Prawdziwy właściciel konta ma dobę, żeby zareagować,
gdy prosi ktoś, kto ukradł mu hasło. `--wykonaj` odmawia bez zapowiedzi
sprzed co najmniej 24 h (i nie starszej niż 7 dni); wtedy w jednej transakcji
usuwa składnik i kody, kończy sesje i zapisuje wpis, a potem wysyła ostrzeżenie.

Dlaczego polecenie, a nie Django shell: ręczne `DrugiSkladnik.objects...delete()`
nie kończy sesji (ktoś, kto przejął telefon i sesję, zostaje zalogowany),
nie zostawia śladu w dzienniku i nie ostrzega właściciela konta - a to on
pierwszy zauważy, że wyłączenia nie zlecał.
"""

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.mfa_reset import wylacz_drugi_skladnik, wyslij_ostrzezenie
from accounts.models import CustomUser, DrugiSkladnik, WpisDziennika
from accounts.sessions import LoginSession

OBSLUGA = "obsługa Sm-art"
ZNACZNIK_ZAPOWIEDZI = "wylacz_mfa zapowiedz: "
ZNACZNIK_WYKONANIA = "wylacz_mfa: "
OCZEKIWANIE = timedelta(hours=24)
WAZNOSC_ZAPOWIEDZI = timedelta(days=7)
TEMAT_ZAPOWIEDZI = "Prośba o wyłączenie drugiego składnika logowania na Twoim koncie"


def tresc_zapowiedzi(uzytkownik, najwczesniej):
    return (
        f"Dzień dobry,\n\n"
        f"otrzymaliśmy prośbę o wyłączenie drugiego składnika logowania (kod z aplikacji) "
        f"na koncie {uzytkownik.email}, po utracie telefonu.\n\n"
        f"Wyłączymy go najwcześniej {timezone.localtime(najwczesniej):%d.%m.%Y o %H:%M}.\n\n"
        f"JEŚLI TO NIE TY prosiłeś o wyłączenie: odpowiedz na tę wiadomość przed tym terminem "
        f"i od razu zmień hasło przez „Nie pamiętam hasła”. Ktoś mógł podszyć się pod Ciebie.\n"
    )


def _wpis(uzytkownik, sciezka):
    WpisDziennika.objects.create(
        tenant=uzytkownik.tenant,
        uzytkownik=uzytkownik,
        nazwa_uzytkownika=OBSLUGA,
        metoda="CLI",
        sciezka=sciezka[:255],
        status=200,
    )


class Command(BaseCommand):
    help = "Wyłącza drugi składnik osobie, która straciła telefon (docs/utrata-mfa.md)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--zgloszenie",
            required=True,
            help="Jak potwierdzono tożsamość (kanał, data, kto) - trafia do dziennika.",
        )
        krok = parser.add_mutually_exclusive_group()
        krok.add_argument(
            "--zapowiedz",
            action="store_true",
            help="Wysyła mail ostrzegawczy; wyłączenie najwcześniej 24 h później.",
        )
        krok.add_argument("--wykonaj", action="store_true", help="Wyłącza (po zapowiedzi).")

    def handle(self, *args, **opcje):
        zgloszenie = opcje["zgloszenie"].strip()
        if len(zgloszenie) < 10:
            raise CommandError(
                "Opisz w --zgloszenie, jak potwierdzono tożsamość (np. kanał i datę). "
                "To jedyny ślad tej decyzji."
            )
        uzytkownik = CustomUser.objects.filter(email__iexact=opcje["email"].strip()).first()
        if uzytkownik is None:
            raise CommandError("Nie ma konta z tym adresem.")
        skladnik = DrugiSkladnik.objects.filter(uzytkownik=uzytkownik).first()
        sesji = LoginSession.objects.filter(user=uzytkownik, revoked_at__isnull=True).count()

        self.stdout.write(f"Konto:     {uzytkownik.email} ({uzytkownik.role})")
        self.stdout.write(f"Firma:     {uzytkownik.tenant.name if uzytkownik.tenant else '-'}")
        stan = (
            "brak"
            if not skladnik
            else "włączone"
            if skladnik.wlaczony
            else "konfiguracja rozpoczęta"
        )
        self.stdout.write(f"MFA:       {stan}")
        self.stdout.write(f"Sesje:     {sesji} aktywnych")
        if not skladnik:
            self.stdout.write(
                self.style.WARNING("To konto nie ma drugiego składnika - nic do zrobienia.")
            )
            return

        teraz = timezone.now()
        zapowiedz = (
            WpisDziennika.objects.filter(
                uzytkownik=uzytkownik,
                metoda="CLI",
                sciezka__startswith=ZNACZNIK_ZAPOWIEDZI,
                czas__gte=teraz - WAZNOSC_ZAPOWIEDZI,
            )
            .order_by("czas")
            .first()
        )

        if opcje["zapowiedz"]:
            self._zapowiedz(uzytkownik, zgloszenie, teraz)
            return
        if not opcje["wykonaj"]:
            if zapowiedz:
                self.stdout.write(
                    f"Zapowiedź: {timezone.localtime(zapowiedz.czas):%d.%m.%Y %H:%M}, "
                    f"wyłączenie możliwe od "
                    f"{timezone.localtime(zapowiedz.czas + OCZEKIWANIE):%d.%m.%Y %H:%M}."
                )
            self.stdout.write(
                self.style.WARNING(
                    "\nPRÓBA NA SUCHO - nic nie zmieniono. Najpierw --zapowiedz, po 24 h --wykonaj."
                )
            )
            return

        if zapowiedz is None:
            raise CommandError(
                "Brak zapowiedzi z ostatnich 7 dni. Najpierw uruchom z --zapowiedz - osoba "
                "dostanie mail ostrzegawczy, a wyłączenie będzie możliwe po 24 h."
            )
        if teraz - zapowiedz.czas < OCZEKIWANIE:
            raise CommandError(
                "Od zapowiedzi nie minęła doba. Wyłączenie możliwe od "
                f"{timezone.localtime(zapowiedz.czas + OCZEKIWANIE):%d.%m.%Y %H:%M}."
            )

        with transaction.atomic():
            uzytkownik = CustomUser.objects.select_for_update().get(pk=uzytkownik.pk)
            zakonczone = wylacz_drugi_skladnik(uzytkownik, teraz)
            _wpis(uzytkownik, ZNACZNIK_WYKONANIA + zgloszenie)

        self.stdout.write(self.style.SUCCESS(f"\nWyłączone. Zakończono sesji: {zakonczone}."))
        try:
            wyslij_ostrzezenie(uzytkownik, teraz, OBSLUGA)
        except Exception as blad:
            # MFA już wyłączone - cofanie nic nie da, a osoba czeka na dostęp.
            # Operator musi jednak wiedzieć, że ostrzeżenie nie poszło.
            self.stdout.write(
                self.style.ERROR(
                    f"Ostrzeżenie mailem NIE wyszło ({type(blad).__name__}). "
                    f"Powiadom {uzytkownik.email} innym kanałem."
                )
            )
            raise SystemExit(1) from None
        self.stdout.write(f"Ostrzeżenie wysłane na {uzytkownik.email}.")

    def _zapowiedz(self, uzytkownik, zgloszenie, teraz):
        najwczesniej = teraz + OCZEKIWANIE
        try:
            if not send_mail(
                subject=TEMAT_ZAPOWIEDZI,
                message=tresc_zapowiedzi(uzytkownik, najwczesniej),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[uzytkownik.email],
                fail_silently=False,
            ):
                raise RuntimeError("send_mail zwrócił 0")
        except Exception as blad:
            # Bez maila doba oczekiwania nie chroni nikogo: prawdziwy właściciel
            # nie wie, że ma na co reagować. Dlatego wpis zapowiedzi powstaje
            # dopiero po wysłaniu - inaczej po dobie odblokowałby --wykonaj.
            self.stdout.write(
                self.style.ERROR(
                    f"Mail z zapowiedzią NIE wyszedł ({type(blad).__name__}). Zapowiedź "
                    "nie została zapisana - powtórz --zapowiedz po naprawie poczty."
                )
            )
            raise SystemExit(1) from None
        _wpis(uzytkownik, ZNACZNIK_ZAPOWIEDZI + zgloszenie)
        self.stdout.write(
            self.style.SUCCESS(
                f"Zapowiedź wysłana na {uzytkownik.email}. Wyłączenie możliwe od "
                f"{timezone.localtime(najwczesniej):%d.%m.%Y %H:%M} (--wykonaj)."
            )
        )
