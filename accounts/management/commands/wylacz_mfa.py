"""
Wyłączenie drugiego składnika osobie, która straciła telefon i kody zapasowe.

Procedura i weryfikacja tożsamości: docs/utrata-mfa.md. To polecenie jest
jej ostatnim krokiem - uruchamia je operator (Render -> Shell) dopiero PO
potwierdzeniu, że prosi właściciel konta.

    python manage.py wylacz_mfa --email osoba@firma.pl --zgloszenie "opis weryfikacji"
    python manage.py wylacz_mfa --email osoba@firma.pl --zgloszenie "..." --wykonaj

Bez --wykonaj tylko pokazuje, czego dotyczy. Z --wykonaj, w jednej transakcji:
usuwa składnik i kody zapasowe, kończy wszystkie sesje tej osoby, zapisuje
wpis w dzienniku firmy; potem wysyła tej osobie ostrzeżenie mailem.

Dlaczego polecenie, a nie Django shell: ręczne `DrugiSkladnik.objects...delete()`
nie kończy sesji (ktoś, kto przejął telefon i sesję, zostaje zalogowany),
nie zostawia śladu w dzienniku i nie ostrzega właściciela konta - a to on
pierwszy zauważy, że wyłączenia nie zlecał.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser, DrugiSkladnik, KodZapasowy, WpisDziennika
from accounts.sessions import LoginSession

TEMAT = "Drugi składnik logowania na Twoim koncie został wyłączony"


def tresc_ostrzezenia(uzytkownik, kiedy):
    return (
        f"Dzień dobry,\n\n"
        f"{timezone.localtime(kiedy):%d.%m.%Y o %H:%M} obsługa Sm-art wyłączyła drugi składnik "
        f"logowania (kod z aplikacji) na koncie {uzytkownik.email}, na Twoją prośbę po utracie "
        f"telefonu. Wszystkie sesje logowania na tym koncie zostały zakończone.\n\n"
        f"Po zalogowaniu włącz drugi składnik ponownie (Ustawienia konta -> bezpieczeństwo) "
        f"i zapisz nowe kody zapasowe w bezpiecznym miejscu.\n\n"
        f"JEŚLI TO NIE TY prosiłeś o wyłączenie: od razu zmień hasło przez „Nie pamiętam hasła” "
        f"i odpowiedz na tę wiadomość. Ktoś mógł podszyć się pod Ciebie.\n"
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
        parser.add_argument("--wykonaj", action="store_true", help="Bez tego nic nie zmienia.")

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
        if not opcje["wykonaj"]:
            self.stdout.write(
                self.style.WARNING("\nPRÓBA NA SUCHO - nic nie zmieniono. Dopisz --wykonaj.")
            )
            return

        teraz = timezone.now()
        with transaction.atomic():
            uzytkownik = CustomUser.objects.select_for_update().get(pk=uzytkownik.pk)
            KodZapasowy.objects.filter(uzytkownik=uzytkownik).delete()
            DrugiSkladnik.objects.filter(uzytkownik=uzytkownik).delete()
            zakonczone = LoginSession.objects.filter(
                user=uzytkownik, revoked_at__isnull=True
            ).update(revoked_at=teraz)
            WpisDziennika.objects.create(
                tenant=uzytkownik.tenant,
                uzytkownik=uzytkownik,
                nazwa_uzytkownika="obsługa Sm-art",
                metoda="CLI",
                sciezka=f"wylacz_mfa: {zgloszenie}"[:255],
                status=200,
            )

        self.stdout.write(self.style.SUCCESS(f"\nWyłączone. Zakończono sesji: {zakonczone}."))
        try:
            wyslane = send_mail(
                subject=TEMAT,
                message=tresc_ostrzezenia(uzytkownik, teraz),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[uzytkownik.email],
                fail_silently=False,
            )
            if not wyslane:
                raise RuntimeError("send_mail zwrócił 0")
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
