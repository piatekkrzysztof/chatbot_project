"""
Powiadomienia o zużyciu limitu wiadomości.

Wyczerpanie limitu wygląda z zewnątrz jak awaria chatbota: widget przestaje
odpowiadać, a klient dowiaduje się o tym od własnych odwiedzających, jeśli
w ogóle. Alerty mają zamienić cichą awarię w decyzję: dokupić pakiet, przejść
na wyższy plan albo świadomie poczekać do nowego cyklu.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

# Treść zależy od progu, bo to trzy różne sytuacje: uprzedzenie, ostrzeżenie
# i informacja o tym, że bot już nie odpowiada.
TRESCI = {
    80: (
        "Zużyto 80% limitu wiadomości",
        "Twój chatbot wykorzystał {uzyte} z {limit} wiadomości w tym cyklu "
        "({procent}%).\n\nNa razie wszystko działa normalnie — to tylko "
        "uprzedzenie, żeby wyczerpanie limitu Cię nie zaskoczyło.",
    ),
    95: (
        "Zużyto 95% limitu wiadomości",
        "Twój chatbot wykorzystał {uzyte} z {limit} wiadomości w tym cyklu "
        "({procent}%).\n\nPo wyczerpaniu limitu widget przestanie odpowiadać "
        "odwiedzającym aż do początku nowego cyklu. Warto teraz rozważyć "
        "wyższy plan albo dokupienie pakietu.",
    ),
    100: (
        "Limit wiadomości wyczerpany — chatbot nie odpowiada",
        "Twój chatbot wykorzystał cały limit {limit} wiadomości w tym cyklu.\n\n"
        "Widget nie odpowiada już odwiedzającym. Żeby go przywrócić, przejdź "
        "na wyższy plan albo dokup pakiet wiadomości.",
    ),
}


@shared_task
def powiadom_o_zuzyciu(subscription_id, prog):
    """
    Wysyła właścicielowi firmy wiadomość o przekroczeniu progu zużycia.

    Błąd wysyłki logujemy, ale nie podnosimy wyżej: alert jest ważny, lecz nie
    na tyle, żeby awaria poczty miała wywrócić odpowiedź chatbota dla
    odwiedzającego — to zamieniłoby drobny problem w poważny.
    """
    from accounts.models import Subscription

    try:
        subscription = Subscription.objects.select_related("tenant").get(pk=subscription_id)
    except Subscription.DoesNotExist:
        logger.warning("Alert zużycia: brak subskrypcji %s", subscription_id)
        return

    adres = subscription.tenant.owner_email
    if not adres:
        logger.warning(
            "Alert zużycia %s%%: firma %s nie ma adresu e-mail właściciela",
            prog,
            subscription.tenant_id,
        )
        return

    temat, tresc = TRESCI.get(prog, TRESCI[100])
    panel = f"{settings.FRONTEND_URL.rstrip('/')}/subskrypcja"

    wiadomosc = tresc.format(
        uzyte=subscription.current_message_count,
        limit=subscription.message_limit,
        procent=subscription.usage_percent(),
    )

    try:
        send_mail(
            subject=temat,
            message=f"{wiadomosc}\n\nSzczegóły i zmiana planu:\n{panel}\n",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[adres],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Nie udało się wysłać alertu zużycia %s%%", prog)
