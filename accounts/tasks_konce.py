"""
Powiadomienia o końcu subskrypcji.

Wyczerpanie limitu wiadomości miało już swoje alerty (`accounts/tasks.py`),
a wygaśnięcie daty nie miało żadnych — mimo że skutek jest identyczny: widget
przestaje odpowiadać. Zdarzyło się to naprawdę: okres próbny skończył się
w niedzielę, chatbot zamilkł, a właściciel dowiedział się o tym przypadkiem
kilka dni później. Przez ten czas każdy odwiedzający jego stronę dostawał
komunikat o błędzie zamiast odpowiedzi.

Osobny moduł, a nie dopisek do `tasks.py`: tamten dotyczy zużycia w cyklu
rozliczeniowym i ma własny stan (`alert_threshold_sent`). To jest inne
zdarzenie, z innym licznikiem i innym harmonogramem — trzymanie obu w jednym
pliku zaciemniłoby, który stan należy do którego alertu.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

# Treść zależy od progu, bo to dwie różne sytuacje: uprzedzenie i informacja
# o tym, że bot już nie odpowiada.
TRESCI_KONCA = {
    3: (
        "Subskrypcja kończy się za 3 dni",
        "Twoja subskrypcja planu {plan} kończy się {data}.\n\n"
        "Do tego czasu wszystko działa normalnie. Po tej dacie widget "
        "przestanie odpowiadać odwiedzającym Twoją stronę.",
    ),
    0: (
        "Subskrypcja wygasła — chatbot nie odpowiada",
        "Twoja subskrypcja planu {plan} skończyła się {data}.\n\n"
        "Widget nie odpowiada już odwiedzającym: zamiast odpowiedzi widzą "
        "komunikat, że czat jest chwilowo niedostępny. Odnowienie przywraca "
        "go natychmiast, bez żadnych zmian na Twojej stronie.",
    ),
}


@shared_task
def sprawdz_konce_subskrypcji():
    """
    Codzienny przegląd subskrypcji: uprzedza o końcu i informuje o wygaśnięciu.

    Zwraca liczbę wysłanych wiadomości. Bez tej liczby zadanie, które nic nie
    zrobiło, wygląda w logu identycznie jak takie, które się nie wykonało.
    """
    from django.utils import timezone

    from accounts.models import Subscription

    dzisiaj = timezone.now().date()
    wyslane = 0

    for subskrypcja in Subscription.objects.select_related("tenant"):
        prog = subskrypcja.prog_konca_do_powiadomienia(dzisiaj)
        if prog is None:
            continue

        if powiadom_o_koncu(subskrypcja, prog):
            wyslane += 1

        # Znacznik zapisujemy TAKŻE po nieudanej wysyłce. Inaczej firma bez
        # adresu e-mail właściciela generowałaby próbę wysyłki i wpis w logu
        # każdego dnia, bez końca i bez żadnego pożytku.
        subskrypcja.alert_konca_prog = prog
        subskrypcja.alert_konca_dla = subskrypcja.end_date
        subskrypcja.save(update_fields=["alert_konca_prog", "alert_konca_dla"])

    logger.info("Przegląd końców subskrypcji: wysłano %s wiadomości", wyslane)
    return wyslane


def powiadom_o_koncu(subskrypcja, prog):
    """
    Wysyła jedną wiadomość o zbliżającym się albo minionym końcu subskrypcji.

    Zwraca True, gdy wiadomość poszła. Błąd wysyłki logujemy, ale nie
    podnosimy wyżej — z tego samego powodu co przy alertach zużycia: awaria
    poczty u jednej firmy nie może zatrzymać przeglądu pozostałych.
    """
    adres = subskrypcja.tenant.owner_email
    if not adres:
        logger.warning(
            "Alert końca subskrypcji: firma %s nie ma adresu e-mail właściciela",
            subskrypcja.tenant_id,
        )
        return False

    temat, tresc = TRESCI_KONCA[prog]
    panel = f"{settings.FRONTEND_URL.rstrip('/')}/subskrypcja"

    wiadomosc = tresc.format(
        plan=subskrypcja.plan_type,
        data=subskrypcja.end_date.strftime("%d.%m.%Y"),
    )

    try:
        send_mail(
            subject=temat,
            message=f"{wiadomosc}\n\nSzczegóły i odnowienie:\n{panel}\n",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[adres],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Nie udało się wysłać alertu końca subskrypcji")
        return False

    return True
