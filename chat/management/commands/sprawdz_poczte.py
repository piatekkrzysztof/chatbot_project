"""
Sprawdzenie konfiguracji poczty na TEJ usłudze — łącznie z siecią.

Kontrola przy starcie (chat/kontrola_poczty.py) wyłapuje błędne kształty
wartości, ale nie wyłapie literówki w poprawnie zbudowanej nazwie hosta:
"stmp.resend.com" wygląda jak nazwa domenowa i dopiero DNS mówi, że takiej
nie ma. Tu naprawdę łączymy się z serwerem i logujemy.

Uruchamiać na tej usłudze, której konfigurację chcemy sprawdzić. Powłoka
Rendera daje dostęp wyłącznie do procesu web — konfigurację workera bada
zadanie `sprawdz_poczte_task`, patrz chat/tasks.py.
"""

import smtplib

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.management.base import BaseCommand

from chat.kontrola_poczty import problemy_z_konfiguracja


def zbadaj_poczte(adres_testowy=None):
    """
    Zwraca listę wierszy raportu. Bez wyjątków — raport ma dojść zawsze,
    także (a zwłaszcza) gdy coś nie działa.
    """
    wiersze = [
        f"host:    {settings.EMAIL_HOST}:{settings.EMAIL_PORT} "
        f"(SSL={settings.EMAIL_USE_SSL}, TLS={settings.EMAIL_USE_TLS})",
        f"login:   {settings.EMAIL_HOST_USER or '(puste)'} "
        f"| hasło ustawione: {bool(settings.EMAIL_HOST_PASSWORD)}",
        f"nadawca: {settings.DEFAULT_FROM_EMAIL or '(puste)'}",
    ]

    problemy = problemy_z_konfiguracja(settings)
    wiersze += [f"KSZTAŁT: {p}" for p in problemy] or ["KSZTAŁT: bez zastrzeżeń"]

    try:
        polaczenie = get_connection(fail_silently=False)
        polaczenie.open()
        polaczenie.close()
        wiersze.append("POŁĄCZENIE: nawiązane i uwierzytelnione")
    except Exception as blad:
        # Rozdzielamy przyczyny, bo prowadzą do różnych miejsc w panelu:
        # nierozwiązana nazwa to EMAIL_HOST, odrzucone logowanie to klucz API.
        if isinstance(blad, OSError) and "not known" in str(blad):
            wiersze.append(
                f"POŁĄCZENIE: nie ma takiego hosta ({settings.EMAIL_HOST}) — "
                f"sprawdź literówkę w EMAIL_HOST. [{type(blad).__name__}]"
            )
        elif isinstance(blad, smtplib.SMTPAuthenticationError):
            wiersze.append(f"POŁĄCZENIE: serwer odrzucił logowanie — {blad}")
        else:
            wiersze.append(f"POŁĄCZENIE: {type(blad).__name__}: {blad}")
        return wiersze

    if not adres_testowy:
        wiersze.append("WYSYŁKA: pominięta (podaj adres, żeby wysłać próbny list)")
        return wiersze

    try:
        send_mail(
            subject="Sprawdzenie poczty",
            message="Jeśli to czytasz, wysyłka z tej usługi działa.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[adres_testowy],
            fail_silently=False,
        )
        wiersze.append(f"WYSYŁKA: przyjęta przez serwer, adresat {adres_testowy}")
    except Exception as blad:
        # Tu wychodzi błędny NADAWCA: połączenie i logowanie już przeszły,
        # a serwer odrzuca dopiero samą kopertę (kod 501).
        wiersze.append(f"WYSYŁKA: {type(blad).__name__}: {blad}")

    return wiersze


class Command(BaseCommand):
    help = "Sprawdza konfigurację poczty na tej usłudze (kształt + realne połączenie)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wyslij",
            metavar="ADRES",
            help="Wyślij próbny list na ten adres (bez tego tylko połączenie)",
        )

    def handle(self, *args, **options):
        for wiersz in zbadaj_poczte(options.get("wyslij")):
            self.stdout.write(wiersz)
