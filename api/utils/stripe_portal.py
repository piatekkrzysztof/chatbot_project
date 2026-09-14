"""
Portal klienta Stripe: zmiana planu, karta, faktury i anulowanie (F11, część 2).

Zmiana planu z panelu była zablokowana, bo jedyną drogą był drugi zakup, czyli
druga subskrypcja i dwa obciążenia co miesiąc. Portal zmienia plan na TEJ SAMEJ
subskrypcji. Stripe sam liczy dopłatę, obsługuje 3D Secure i pokazuje faktury -
w panelu trzeba by to wszystko zbudować i utrzymywać.

Zasady rozliczeń (decyzja właściciela z 14.09.2026):

* wyższy plan od razu, z dopłatą proporcjonalną za resztę okresu
  (`always_invoice` - faktura na różnicę powstaje od razu, a nie przy
  odnowieniu),
* niższy plan od następnego okresu (`schedule_at_period_end`) - bez zwrotów
  i korekt faktur,
* anulowanie z końcem opłaconego okresu,
* dane do faktury zmienia się w panelu, nie w portalu (`customer_update`
  wyłączone) - inaczej NIP w Stripe rozjechałby się z danymi firmy.

Konfigurację zakładamy z kodu, a nie klikamy w panelu Stripe. Tryb testowy
i produkcyjny mają osobne konfiguracje, a dwa razy ustawione ręcznie to dwa
miejsca, z których ktoś kiedyś zmieni tylko jedno.
"""

import hashlib
import logging

import stripe
from django.conf import settings
from django.core.cache import cache

from api.views.stripe_webhook import _identyfikator

logger = logging.getLogger(__name__)

#: Podnieś przy każdej zmianie `parametry_konfiguracji`. Istniejąca konfiguracja
#: w Stripe się nie zmieni - nowa wersja zakłada nową, a stara zostaje nieużywana.
WERSJA_KONFIGURACJI = "1"

#: Klucz w metadanych konfiguracji, po którym ją odnajdujemy.
ZNACZNIK = "sm_art_portal"

CZAS_PAMIETANIA_SEKUND = 60 * 60


def oznaczenie_konfiguracji():
    """
    Wersja kodu plus to, od czego zależy treść konfiguracji.

    Nowa cena w zmiennych środowiskowych albo nowy adres panelu dają nowe
    oznaczenie, więc portal nie zostanie przy nieaktualnym cenniku.
    """
    zrodlo = "|".join(
        [
            WERSJA_KONFIGURACJI,
            settings.FRONTEND_URL.rstrip("/"),
            *(f"{kod}={cena}" for kod, cena in sorted(settings.STRIPE_PRICE_IDS.items())),
        ]
    )
    return f"{WERSJA_KONFIGURACJI}-{hashlib.sha256(zrodlo.encode()).hexdigest()[:12]}"


def parametry_konfiguracji(oznaczenie):
    """Treść konfiguracji portalu. Każda zmiana tutaj wymaga nowej wersji."""
    produkty = {}
    for cena in settings.STRIPE_PRICE_IDS.values():
        if cena:
            produkt = _identyfikator(stripe.Price.retrieve(cena).get("product"))
            produkty.setdefault(produkt, []).append(cena)

    zmiana_planu = {"enabled": False}
    if produkty:
        zmiana_planu = {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "products": [
                {"product": produkt, "prices": ceny} for produkt, ceny in produkty.items()
            ],
            "proration_behavior": "always_invoice",
            "schedule_at_period_end": {
                "conditions": [
                    {"type": "decreasing_item_amount"},
                    {"type": "shortening_interval"},
                ]
            },
        }

    return {
        "business_profile": {"headline": "Sm-art - zarządzanie subskrypcją chatbota"},
        "default_return_url": f"{settings.FRONTEND_URL.rstrip('/')}/subskrypcja",
        "features": {
            "customer_update": {"enabled": False},
            "invoice_history": {"enabled": True},
            "payment_method_update": {"enabled": True},
            "subscription_cancel": {
                "enabled": True,
                "mode": "at_period_end",
                "proration_behavior": "none",
            },
            "subscription_update": zmiana_planu,
        },
        "metadata": {ZNACZNIK: oznaczenie},
    }


def _klucz_pamieci(oznaczenie):
    return f"stripe-portal-{oznaczenie}"


def konfiguracja_portalu():
    """Identyfikator konfiguracji portalu dla bieżących cen - istniejącej albo nowej."""
    oznaczenie = oznaczenie_konfiguracji()
    zapamietana = cache.get(_klucz_pamieci(oznaczenie))
    if zapamietana:
        return zapamietana

    identyfikator = None
    for konfiguracja in stripe.billing_portal.Configuration.list(
        active=True, limit=100
    ).auto_paging_iter():
        if (konfiguracja.get("metadata") or {}).get(ZNACZNIK) == oznaczenie:
            identyfikator = konfiguracja["id"]
            break

    if identyfikator is None:
        # Klucz idempotencji: dwa pierwsze otwarcia portalu naraz nie założą
        # dwóch konfiguracji.
        identyfikator = stripe.billing_portal.Configuration.create(
            idempotency_key=f"portal-konfiguracja-{oznaczenie}",
            **parametry_konfiguracji(oznaczenie),
        )["id"]
        logger.info("Założono konfigurację portalu Stripe %s (%s)", identyfikator, oznaczenie)

    cache.set(_klucz_pamieci(oznaczenie), identyfikator, CZAS_PAMIETANIA_SEKUND)
    return identyfikator


def zapomnij_konfiguracje():
    """Po błędzie Stripe: następne otwarcie sprawdzi konfigurację od nowa."""
    cache.delete(_klucz_pamieci(oznaczenie_konfiguracji()))
