"""
Odbiór zdarzeń ze Stripe.

Historia: ten kod długo nie działał wcale - nie był podpięty pod URL, a potem
aktualizował pola na Tenant zamiast Subscription, którą egzekwuje middleware.
Źródłem prawdy o dostępie jest Subscription i to ona zmienia się po płatności.

Synchronizacja zamiast poleceń (F11)
------------------------------------
Wcześniej każde zdarzenie było poleceniem: „zapłacono - aktywuj na 31 dni",
„nieudana płatność - zawieś", „usunięto - zawieś". Stripe nie gwarantuje
kolejności zdarzeń, ponawia je do trzech dni i dostarcza czasem podwójnie,
więc polecenia wykonane po kolei dawały stany, których w Stripe nie było:

  * powtórzony stary `checkout.session.completed` po anulowaniu przywracał
    dostęp na 31 dni bez płatności,
  * spóźnione `invoice.payment_failed` po udanej płatności zawieszało
    opłaconego klienta,
  * pierwsza nieudana próba odnowienia odcinała czat od razu, choć Stripe
    ponawia płatność przez kilka dni,
  * `customer.subscription.deleted` STAREJ subskrypcji zawieszało nową,
  * sesja zakończona bez zapłaty aktywowała plan,
  * okres był zawsze „dziś + 31 dni", także przy planie rocznym,
  * zmiana planu po stronie Stripe nie docierała wcale.

Teraz zdarzenie jest tylko sygnałem, KTÓREJ subskrypcji dotyczy. Webhook
pobiera jej aktualny stan ze Stripe i przepisuje go do bazy. Powtórka,
duplikat i zła kolejność dają ten sam wynik, bo stan jest zawsze bieżący.
"""

import logging
from datetime import UTC, datetime, timedelta

import stripe
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from accounts.models import Subscription, Tenant
from accounts.plans import get_plan

logger = logging.getLogger(__name__)

#: Zapas za końcem opłaconego okresu. Stripe ponawia nieudaną płatność przez
#: kilka dni; w tym czasie klient korzysta dalej, a po udanym ponowieniu okres
#: przesuwa się sam. Decyzja właściciela z 13.09.2026: dostęp do końca
#: opłaconego okresu, nie odcięcie przy pierwszej nieudanej próbie.
BUFOR_PONOWIEN = timedelta(days=3)

#: Statusy Stripe, przy których firma ma dostęp. `past_due` tylko do końca
#: OSTATNIEGO OPŁACONEGO okresu - Stripe przesuwa okres na nowy także wtedy,
#: gdy płatność za niego nie przeszła.
STATUSY_Z_DOSTEPEM = frozenset({"active", "trialing", "past_due"})

#: Statusy końcowe albo wstrzymane - dostęp wygasa. `incomplete` (pierwsza
#: płatność jeszcze nie przeszła) nie należy do żadnej grupy: nie aktywuje
#: i nie zawiesza niczego, co już działa.
STATUSY_BEZ_DOSTEPU = frozenset({"canceled", "unpaid", "incomplete_expired", "paused"})


class ZdarzenieDoPonowienia(Exception):
    """Przejściowy błąd Stripe - webhook oddaje 500, żeby Stripe ponowił."""


def _data(znacznik_czasu):
    return datetime.fromtimestamp(int(znacznik_czasu), tz=UTC).date()


def _identyfikator(wartosc):
    """Pole bywa samym identyfikatorem albo rozwiniętym obiektem."""
    if isinstance(wartosc, dict):
        return wartosc.get("id") or ""
    return wartosc or ""


def identyfikator_subskrypcji(event_type, obiekt):
    """
    Której subskrypcji dotyczy zdarzenie - albo pusty ciąg.

    Adres subskrypcji na fakturze przesuwał się między wersjami API Stripe,
    dlatego faktura ma kilka miejsc do sprawdzenia.
    """
    if event_type.startswith("customer.subscription."):
        return _identyfikator(obiekt.get("id"))
    if event_type.startswith("checkout.session."):
        return _identyfikator(obiekt.get("subscription"))
    if event_type.startswith("invoice."):
        szczegoly = (
            (obiekt.get("parent") or {}).get("subscription_details")
            or obiekt.get("subscription_details")
            or {}
        )
        return _identyfikator(szczegoly.get("subscription")) or _identyfikator(
            obiekt.get("subscription")
        )
    return ""


def pobierz_subskrypcje(identyfikator):
    """
    Aktualny stan subskrypcji ze Stripe.

    None, gdy subskrypcja nie istnieje (np. zdarzenie z innego trybu) -
    ponawianie nic nie da. Błąd przejściowy (sieć, limit, awaria Stripe)
    rzuca ZdarzenieDoPonowienia: bez bieżącego stanu nie ma czego zapisać,
    a Stripe ponowi zdarzenie z odstępami.
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        # Harmonogram w tym samym zapytaniu: zaplanowana obniżka jest tylko
        # tam, sama subskrypcja do dnia zmiany pokazuje dotychczasową cenę.
        return stripe.Subscription.retrieve(identyfikator, expand=["schedule"])
    except stripe.error.InvalidRequestError:
        logger.warning("Subskrypcja %s nie istnieje w Stripe - pomijam zdarzenie", identyfikator)
        return None
    except stripe.error.StripeError as blad:
        raise ZdarzenieDoPonowienia(str(blad)) from blad


def plan_z_subskrypcji(subskrypcja):
    """
    Plan po identyfikatorze ceny, a metadane tylko w ostateczności.

    Metadane ustawiamy przy zakupie i nie zmieniają się, gdy plan zmieni się
    po stronie Stripe. Cena mówi, za co klient faktycznie płaci.
    """
    return _plan_z_pozycji((subskrypcja.get("items") or {}).get("data")) or (
        subskrypcja.get("metadata") or {}
    ).get("plan")


def _plan_z_pozycji(pozycje):
    ceny = {cena: kod for kod, cena in settings.STRIPE_PRICE_IDS_ROCZNE.items() if cena}
    ceny.update({cena: kod for kod, cena in settings.STRIPE_PRICE_IDS.items() if cena})
    for pozycja in pozycje or []:
        cena = _identyfikator(pozycja.get("price"))
        if cena in ceny:
            return ceny[cena]
    return None


def zaplanowana_zmiana_planu(subskrypcja):
    """
    (kod planu, data) następnej fazy harmonogramu, gdy zmienia plan - albo (None, None).

    Obniżka z portalu to harmonogram: bieżąca faza z dotychczasową ceną do końca
    okresu, następna z niższą. Anulowanie z końcem okresu zostawia harmonogram
    bez następnej fazy, więc tu nic nie znajdzie - to widać po `cancel_at`.
    """
    harmonogram = subskrypcja.get("schedule")
    if not isinstance(harmonogram, dict):
        return None, None
    koniec_biezacej = (harmonogram.get("current_phase") or {}).get("end_date")
    if not koniec_biezacej:
        return None, None
    obecny = plan_z_subskrypcji(subskrypcja)
    for faza in harmonogram.get("phases") or []:
        if faza.get("start_date") and faza["start_date"] >= koniec_biezacej:
            kod = _plan_z_pozycji(faza.get("items"))
            if kod and kod != obecny:
                return kod, _data(faza["start_date"])
            return None, None
    return None, None


def data_anulowania(subskrypcja):
    """Dzień, w którym Stripe zakończy subskrypcję - albo None, gdy się odnawia."""
    if subskrypcja.get("cancel_at"):
        return _data(subskrypcja["cancel_at"])
    if subskrypcja.get("cancel_at_period_end"):
        return _data(subskrypcja["current_period_end"])
    return None


def _powiadom_o_nieudanej_platnosci(subscription_id):
    from accounts.tasks_konce import powiadom_o_nieudanej_platnosci
    from documents.utils.queue import enqueue

    try:
        enqueue(powiadom_o_nieudanej_platnosci, subscription_id)
    except Exception:
        # Zapis stanu już się odbył - brak kolejki nie może cofnąć dostępu
        # ani kazać Stripe'owi ponawiać zdarzenia.
        logger.exception(
            "Nie udało się zlecić powiadomienia o nieudanej płatności: subskrypcja=%s",
            subscription_id,
        )


def synchronizuj_subskrypcje(tenant, subskrypcja_stripe):
    """
    Przepisuje stan subskrypcji ze Stripe do Subscription firmy.

    Pod blokadą wiersza firmy: dwa zdarzenia tej samej subskrypcji naraz
    (zakup wysyła zwykle dwa w tej samej sekundzie) nie mogą założyć dwóch
    wierszy ani nadpisać się w połowie. Wywołanie Stripe dzieje się wcześniej,
    poza blokadą.
    """
    sid = subskrypcja_stripe["id"]
    status = subskrypcja_stripe.get("status") or ""

    with transaction.atomic():
        Tenant.objects.select_for_update().only("id").get(pk=tenant.pk)
        lokalna = Subscription.objects.select_for_update().filter(tenant=tenant).first()
        powiazana = bool(lokalna and lokalna.stripe_subscription_id == sid)

        if lokalna and lokalna.stripe_subscription_id and not powiazana:
            if status not in STATUSY_Z_DOSTEPEM:
                # Zdarzenie o subskrypcji, która nie jest (już) subskrypcją tej
                # firmy - np. usunięcie starej po zakupie nowej.
                logger.info(
                    "Subskrypcja %s (%s) nie jest subskrypcją firmy %s - pomijam",
                    sid,
                    status,
                    tenant.id,
                )
                return lokalna
            if lokalna.is_active and lokalna.stripe_status in STATUSY_Z_DOSTEPEM:
                # Nie przełączamy w tę i z powrotem przy kolejnych zdarzeniach
                # obu subskrypcji. Checkout blokuje drugi zakup, więc to stan
                # awaryjny do wyjaśnienia ręcznie, w tym ewentualny zwrot.
                logger.error(
                    "Firma %s ma dwie aktywne subskrypcje Stripe: %s i %s - zostawiam %s",
                    tenant.id,
                    lokalna.stripe_subscription_id,
                    sid,
                    lokalna.stripe_subscription_id,
                )
                return lokalna

        if status in STATUSY_Z_DOSTEPEM:
            poprzedni_status = lokalna.stripe_status if powiazana else ""
            kod_planu = plan_z_subskrypcji(subskrypcja_stripe)
            plan = get_plan(kod_planu)
            poczatek = _data(subskrypcja_stripe["current_period_start"])
            koniec_oplaconego = (
                poczatek
                if status == "past_due"
                else _data(subskrypcja_stripe["current_period_end"])
            )
            koniec = koniec_oplaconego + BUFOR_PONOWIEN
            anulowanie = data_anulowania(subskrypcja_stripe)
            if anulowanie:
                # Anulowana subskrypcja kończy się w Stripe dokładnie tego dnia.
                # Zapas na ponowienia płatności nie ma sensu, skoro płatności
                # już nie będzie - a panel i alert końca pokazywały datę o trzy
                # dni za późną.
                koniec = min(koniec, anulowanie)
            zaplanowany, zaplanowany_od = zaplanowana_zmiana_planu(subskrypcja_stripe)
            pola = {
                "plan_type": plan.code if plan else (kod_planu or "unknown"),
                "message_limit": plan.message_limit if plan else 1_000,
                "is_active": True,
                "start_date": poczatek,
                "end_date": koniec,
                "stripe_subscription_id": sid,
                "stripe_status": status,
                "anulowanie_od": anulowanie,
                "zaplanowany_plan": zaplanowany or "",
                "zaplanowany_plan_od": zaplanowany_od,
            }
            if lokalna is None:
                lokalna = Subscription.objects.create(tenant=tenant, **pola)
            else:
                for pole, wartosc in pola.items():
                    setattr(lokalna, pole, wartosc)
                lokalna.save(update_fields=list(pola))

            # Pola na Tenant są tylko odbiciem stanu - panel admina po nich filtruje.
            tenant.subscription_status = "past_due" if status == "past_due" else "active"
            tenant.subscription_plan = pola["plan_type"]
            tenant.save(update_fields=["subscription_status", "subscription_plan"])

            # Jedna wiadomość na wejście w past_due, nie na każde zdarzenie:
            # nieudana płatność przychodzi jako kilka zdarzeń naraz, a Stripe
            # ponawia je i pobiera kolejne próby. Blokada wiersza firmy
            # gwarantuje, że przejście zobaczy tylko jedno z nich.
            if status == "past_due" and poprzedni_status != "past_due":
                identyfikator_wiersza = lokalna.pk
                transaction.on_commit(
                    lambda: _powiadom_o_nieudanej_platnosci(identyfikator_wiersza)
                )
            return lokalna

        if powiazana and status in STATUSY_BEZ_DOSTEPU:
            lokalna.is_active = False
            lokalna.stripe_status = status
            lokalna.anulowanie_od = None
            lokalna.zaplanowany_plan = ""
            lokalna.zaplanowany_plan_od = None
            lokalna.save(
                update_fields=[
                    "is_active",
                    "stripe_status",
                    "anulowanie_od",
                    "zaplanowany_plan",
                    "zaplanowany_plan_od",
                ]
            )
            tenant.subscription_status = "suspended"
            tenant.save(update_fields=["subscription_status"])
            logger.warning("Subskrypcja wstrzymana (%s): tenant=%s", status, tenant.id)
            return lokalna

        logger.info(
            "Subskrypcja %s w stanie %s - dostęp firmy %s bez zmian", sid, status, tenant.id
        )
        return lokalna


# csrf_exempt MUSI stać bezpośrednio nad tym widokiem. Stripe wysyła POST bez
# ciasteczka sesji i bez tokenu CSRF, więc bez tego Django odrzuca każde
# zdarzenie kodem 403 — zanim kod webhooka w ogóle się wykona. W panelu Stripe
# wygląda to jak nieudana dostawa, a w bazie nie dzieje się nic.
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        logger.warning("Nieprawidłowa treść żądania ze Stripe")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        # Bez poprawnego podpisu każdy mógłby aktywować sobie dowolny plan
        logger.warning("Błędna sygnatura webhooka Stripe")
        return HttpResponse(status=400)

    event_type = event["type"]
    obiekt = event["data"]["object"]
    identyfikator = identyfikator_subskrypcji(event_type, obiekt)
    if not identyfikator:
        # 200, nie błąd: kod błędu kazałby Stripe'owi ponawiać zdarzenie,
        # którego nie ma jak obsłużyć.
        logger.info("Zdarzenie %s nie dotyczy subskrypcji - pomijam", event_type)
        return HttpResponse(status=200)

    try:
        subskrypcja = pobierz_subskrypcje(identyfikator)
    except ZdarzenieDoPonowienia:
        logger.exception("Stripe niedostępny przy zdarzeniu %s - czekam na ponowienie", event_type)
        return HttpResponse(status=500)
    if subskrypcja is None:
        return HttpResponse(status=200)

    tenant_id = str(
        (subskrypcja.get("metadata") or {}).get("tenant_id")
        or (obiekt.get("metadata") or {}).get("tenant_id")
        or ""
    )
    tenant = Tenant.objects.filter(id=int(tenant_id)).first() if tenant_id.isdigit() else None
    if tenant is None:
        logger.warning(
            "Zdarzenie %s (subskrypcja %s) bez znanej firmy - pomijam", event_type, identyfikator
        )
        return HttpResponse(status=200)

    stan = synchronizuj_subskrypcje(tenant, subskrypcja)
    logger.info(
        "Stripe %s: tenant=%s plan=%s aktywna=%s status=%s",
        event_type,
        tenant.id,
        getattr(stan, "plan_type", None),
        getattr(stan, "is_active", None),
        getattr(stan, "stripe_status", None),
    )
    return HttpResponse(status=200)
