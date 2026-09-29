"""
Codzienne czuwanie nad rezerwacjami AI.

Dwie rzeczy, obie proste, obu do dzisiaj nie robił nikt: powiedzieć, że są
bilety do rozliczenia, i usunąć te, które rozliczono kwartał temu. Powód, dla
którego bilet zostaje nierozliczony, i powód, dla którego nikt tego nie
rozlicza automatycznie, opisuje `accounts/rezerwacje.py`.

Alert przychodzi codziennie, dopóki jest co rozliczać - nie ma tu znacznika
„zgłoszone" jak przy odmowach widgetu. Przy odmowach znacznik jest po to, żeby
jedna trwająca przyczyna nie wysyłała wiadomości co godzinę. Tutaj każdy bilet
to osobna decyzja człowieka i dopóki jej nie ma, sprawa nie jest załatwiona;
powtórka raz na dobę jest przypomnieniem, a nie szumem. Gdyby kiedyś zaczęła
nim być, znaczyłoby to, że mamy dużo nierozliczonych biletów - i wtedy problem
jest po stronie rozliczania, nie alertu.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from accounts import rezerwacje
from accounts.czuwanie import adres_operatora

logger = logging.getLogger(__name__)

#: Ile biletów wypisujemy w treści alertu. Reszta jest w komendzie - wiadomość
#: ma skłonić do jej uruchomienia, a nie zastąpić ją listą na sto pozycji.
NAJWIECEJ_W_ALERCIE = 20


def _tresc_alertu(bilety, ile):
    akapity = [
        "Rezerwacje pracy AI czekają na rozliczenie. Każda z nich zajmuje "
        "klientowi jedną wiadomość z limitu do końca bieżącego cyklu, choć "
        "nie wiadomo, czy bot w ogóle odpowiedział.",
        "",
    ]
    for bilet in bilety:
        powstal = timezone.localtime(bilet.created_at).strftime("%d.%m.%Y %H:%M")
        akapity.append(f"• {bilet.pk}")
        akapity.append(f"  Firma: {bilet.tenant_id}, stan: {bilet.state}, powstał: {powstal}")
        akapity.append("")

    if ile > len(bilety):
        akapity.append(f"...oraz {ile - len(bilety)} dalszych. Pełna lista:")
        akapity.append("")
    akapity.append("    python manage.py check_message_reservations")
    akapity.append("")
    akapity.append("Rozliczenie jednego biletu, po ustaleniu, czy praca została wykonana:")
    akapity.append("")
    akapity.append(
        "    python manage.py check_message_reservations --reservation UUID "
        "--outcome charged|released"
    )
    akapity.append("")
    akapity.append(
        "Nic nie rozliczy się samo: stan „uncertain” znaczy, że nie wiemy, "
        "czy zapytanie doszło do OpenAI, a zgadywanie w którąkolwiek stronę "
        "kosztuje albo klienta, albo nas."
    )
    return "\n".join(akapity)


def _wyslij_alert(bilety, ile):
    wyslane = send_mail(
        subject=f"Rezerwacje AI do rozliczenia: {ile}",
        message=_tresc_alertu(bilety, ile),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[adres_operatora()],
        fail_silently=False,
    )
    if not wyslane:
        # Zero doręczeń bez wyjątku - tak Django kończy wysyłkę do pustej
        # listy odbiorców i tak zachowuje się backend, który po cichu odrzuca
        # wiadomość. Bez tego sprawdzenia nie odróżnilibyśmy tego od sukcesu.
        raise RuntimeError("send_mail zwrócił 0 - alert nie został doręczony")


@shared_task
def czuwaj_nad_rezerwacjami():
    """
    Zgłasza bilety do rozliczenia i sprząta rozliczone.

    Zwraca liczby także przy zerach i zapisuje je do logu, bo cisza nie
    odróżnia przebiegu, który nic nie znalazł, od przebiegu, którego nie było.
    Tę pomyłkę popełnił już monitor kopii i popełniły ją trzy martwe zadania.
    """
    teraz = timezone.now()
    czekajace = list(rezerwacje.nierozliczone(teraz)[:NAJWIECEJ_W_ALERCIE])
    ile = rezerwacje.nierozliczone(teraz).count()

    # Sprzątanie PRZED alertem, nie po nim. Gdy poczta nie działa, wysyłka
    # rzuca wyjątkiem i wszystko za nią zostałoby pominięte - a usuwanie
    # biletów sprzed kwartału nie ma nic wspólnego z tym, czy alert doszedł.
    usuniete = rezerwacje.usun_rozliczone(teraz)

    logger.info(
        "Rezerwacje: do rozliczenia %s, usuniętych rozliczonych %s",
        ile,
        usuniete,
    )
    if ile:
        _wyslij_alert(czekajace, ile)
    return {"nierozliczone": ile, "usuniete": usuniete}
