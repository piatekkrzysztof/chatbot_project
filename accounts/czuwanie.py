"""
Czuwanie nad tym, czy chatboty klientów odpowiadają.

Raport z incydentu 26.08.2026 kończy się trzema zdaniami, które są tu
specyfikacją:

  • „The refusal path still writes no log line."
  • „No monitoring exists."
  • „The check that found this was manual. A step on a checklist a person
    walks through is not detection. It happened to be there."

Pierwsze zamyka `accounts/odmowy.py`. Ten moduł zamyka dwa pozostałe: nikt
nie musi niczego otwierać ani odhaczać, żeby dowiedzieć się, że u któregoś
klienta widget przestał odpowiadać.

Dlaczego alert idzie do operatora, a nie do właściciela
------------------------------------------------------
Właściciel ma już swoje powiadomienia: o zbliżającym się końcu subskrypcji
(`tasks_konce.py`) i o zużyciu limitu (`tasks.py`). Brakującym odbiorcą jesteśmy
my - w sierpniu chatbot milczał na naszej własnej stronie i nie dowiedział się
o tym nikt. Alert ma trafić tam, gdzie ktoś może naprawić także przypadek,
którego właściciel nie rozumie.

Czego to NIE wykrywa
--------------------
Licznik odmów jest reaktywny: zapisuje się dopiero wtedy, gdy ktoś odwiedzi
stronę klienta i napisze do bota. Subskrypcja, która wygasła w nocy na stronie
bez ruchu, nie odłoży ani jednej odmowy - i alert nie pójdzie, bo nikt jeszcze
nie ucierpiał. Uprzedzenie o samej dacie należy do `tasks_konce.py` i to ono
pokrywa ten przypadek; tutaj wykrywamy skutek, tam przyczynę. Dopiero razem
domykają jedno i drugie.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from accounts.odmowy import POWODY_ALARMUJACE, PowodOdmowy, ZliczenieOdmow

logger = logging.getLogger(__name__)

#: Ile nieznanych kluczy w ciągu doby zaczyna coś znaczyć.
#:
#: Pojedyncze trafienia to szum: stary fragment na czyjejś porzuconej stronie,
#: skaner, czyjś test. Dopiero seria mówi o czymś realnym - najczęściej o tym,
#: że klient wkleił widget z literówką i jego czat w ogóle nie ruszył.
PROG_ZLYCH_KLUCZY = 50


def _adres_operatora() -> str:
    """
    Dokąd idą alerty.

    Osobna zmienna, a nie `DEFAULT_FROM_EMAIL`, bo to dwie różne role: z tamtego
    adresu piszemy do klientów, a ten ktoś musi czytać w niedzielę. Gdy nie jest
    ustawiona, wracamy do adresu nadawcy - alert wysłany do siebie jest wciąż
    lepszy niż alert nigdzie.
    """
    return getattr(settings, "EMAIL_ALERTOW", "") or settings.DEFAULT_FROM_EMAIL


def _opis_firmy(zliczenie: ZliczenieOdmow) -> str:
    if zliczenie.tenant:
        return f"{zliczenie.tenant.name} (klucz {str(zliczenie.tenant.api_key)[:8]}...)"
    return "nieznana firma - klucz API nie pasuje do żadnego konta"


def _tresc_alertu(zliczenia) -> str:
    """Buduje wiadomość: co, u kogo, od kiedy i ilu ludzi to dotknęło."""
    akapity = [
        "Widget odmawia obsługi odwiedzającym. Każda odmowa to ktoś, kto "
        "otworzył czat na stronie klienta i nie dostał odpowiedzi.",
        "",
    ]

    for z in zliczenia:
        od = timezone.localtime(z.pierwsza).strftime("%H:%M")
        do = timezone.localtime(z.ostatnia).strftime("%H:%M")
        akapity.append(f"• {_opis_firmy(z)}")
        akapity.append(f"  Powód: {z.get_powod_display()}")
        akapity.append(f"  Odmów dzisiaj: {z.liczba}, od {od} do {do}")
        akapity.append("")

    akapity.append(
        "Dopóki przyczyna trwa, ta wiadomość przyjdzie raz na dobę - nie po każdej odmowie."
    )
    return "\n".join(akapity)


@shared_task
def sprawdz_odmowy_widgetu():
    """
    Zgłasza firmy, którym widget dziś odmawia.

    Uruchamiane co godzinę. Dobowy odstęp byłby niewiele lepszy od przypadku,
    który znalazł awarię w sierpniu - ta trwała około doby. Godzina kosztuje
    jedno zapytanie i skraca czas do zauważenia z dnia do kwadransa.

    Zwraca liczbę zgłoszonych wierszy, żeby wywołanie z konsoli mówiło,
    czy coś się wydarzyło.
    """
    dzis = timezone.localdate()

    # Nieznane klucze wchodzą dopiero powyżej progu, reszta natychmiast:
    # pojedynczy skaner to nie jest awaria, a jedna odmowa z powodu wygasłej
    # subskrypcji już nią jest.
    do_zgloszenia = ZliczenieOdmow.objects.filter(
        Q(powod__in=POWODY_ALARMUJACE)
        | Q(powod=PowodOdmowy.ZLY_KLUCZ, liczba__gte=PROG_ZLYCH_KLUCZY)
        | Q(powod=PowodOdmowy.BRAK_KLUCZA, liczba__gte=PROG_ZLYCH_KLUCZY),
        dzien=dzis,
        zgloszone=False,
    ).select_related("tenant")

    zliczenia = list(do_zgloszenia)
    if not zliczenia:
        return 0

    temat = (
        f"Chatbot nie odpowiada: {len(zliczenia)} "
        f"{'zgłoszenie' if len(zliczenia) == 1 else 'zgłoszenia'}"
    )

    try:
        send_mail(
            subject=temat,
            message=_tresc_alertu(zliczenia),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[_adres_operatora()],
            fail_silently=False,
        )
    except Exception:
        # Znacznika NIE stawiamy: nieudana wysyłka nie może uchodzić za
        # doręczoną, bo alert przepadłby na zawsze - następne uruchomienie
        # uznałoby sprawę za załatwioną. Lepiej spróbować za godzinę.
        logger.exception("Nie udalo sie wyslac alertu o odmowach widgetu")
        raise

    # Dopiero po udanej wysyłce.
    ZliczenieOdmow.objects.filter(pk__in=[z.pk for z in zliczenia]).update(zgloszone=True)

    logger.warning(
        "Alert o odmowach widgetu wyslany: %s pozycji, firmy: %s",
        len(zliczenia),
        ", ".join(z.tenant.name if z.tenant else "?" for z in zliczenia),
    )
    return len(zliczenia)
