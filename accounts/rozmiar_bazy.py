"""
Ostrzeżenie, gdy baza wiedzy klienta zbliża się do progu wydajności.

Skąd to się wzięło
------------------
Pomiar na produkcji ([docs/skala-i-wydajnosc.md]) pokazał, że wyszukiwanie
rośnie gorzej niż liniowo, a kolano krzywej leży między 5 a 10 tysiącami
fragmentów. Przy tysiącu jest 90 ms, przy pięciu tysiącach 396 ms, przy
dziesięciu już 1,3 sekundy.

Do tej pory jedynym sposobem, żeby się o tym dowiedzieć, było uruchomienie
komendy pomiarowej i pamiętanie, żeby to zrobić. `docs/adr/001` nazywa ten
brak wprost: „można to obserwować, zamiast na to czekać, a alertu nie ma".

Dlaczego dwa progi, a nie jeden
-------------------------------
Jeden próg odpowiada tylko na pytanie „czy już". Dwa odpowiadają też na „ile
zostało czasu", a to jest różnica między informacją a wezwaniem.

  • 2 500 fragmentów - połowa kolana. Nic się jeszcze nie dzieje: około 220 ms,
    czyli mniej, niż trwa zwykłe wywołanie modelu. Jest czas, żeby spokojnie
    zdecydować, co dalej.
  • 5 000 fragmentów - samo kolano, i zarazem limit planu Start. Od tego
    miejsca każde kolejne tysiąc fragmentów kosztuje więcej niż poprzednie.

Dlaczego do nas, a nie do klienta
---------------------------------
Klient nie ma czym na to zareagować. Nie wie, czym jest fragment, a jedyne, co
mógłby zrobić - skasować część własnej wiedzy - jest odwrotnością tego, po co
kupił produkt. Decyzja (indeks, zmiana limitów, rozmowa o planie) należy do
nas.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.db.models import Count

logger = logging.getLogger(__name__)

#: Połowa zmierzonego kolana. Uprzedzenie, nie alarm.
PROG_UWAGI = 2_500

#: Samo kolano, i zarazem limit planu Start.
PROG_PILNY = 5_000

#: Ile mikrosekund na fragment poniżej kolana.
#:
#: Z pomiaru na produkcji: 1 000 fragmentow -> 90 ms, 5 000 -> 396 ms, czyli
#: okolo 80-90 us na sztuke. Uzywane wylacznie do tego, zeby wiadomosc podawala
#: czas, a nie samą liczbę wierszy - „2 500 fragmentow" nic nie mowi komus,
#: kto nie pamieta tamtej tabeli.
MIKROSEKUND_NA_FRAGMENT = 88


class ZgloszonyRozmiar(models.Model):
    """
    Zapis, że o przekroczeniu tego progu już powiedzieliśmy.

    Klucz to para firma-próg, więc każdy próg odzywa się raz. Baza wiedzy
    skasowana i wgrana od nowa przekroczy próg drugi raz - i nie odezwie się,
    bo o tej firmie już wiemy.
    """

    tenant = models.ForeignKey(
        "accounts.Tenant", on_delete=models.CASCADE, related_name="zgloszone_rozmiary"
    )
    prog = models.PositiveIntegerField()
    fragmentow = models.PositiveIntegerField(help_text="Ile bylo w chwili zgloszenia")
    zgloszone_dnia = models.DateField(auto_now_add=True)

    class Meta:
        verbose_name = "Zgłoszony rozmiar bazy wiedzy"
        verbose_name_plural = "Zgłoszone rozmiary baz wiedzy"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "prog"], name="unikalny_zgloszony_rozmiar")
        ]

    def __str__(self):
        return f"{self.tenant.name}: przekroczyl {self.prog} ({self.fragmentow})"


def firmy_przy_progu() -> list[dict]:
    """
    Firmy, które przekroczyły próg i jeszcze o tym nie mówiliśmy.

    Liczymy WSZYSTKIE fragmenty firmy, także te z dokumentów wyłączonych
    z wyszukiwania. Wyłączony dokument nie bierze udziału w zapytaniu, ale
    klient może go włączyć jednym kliknięciem - a wtedy koszt wraca.
    """
    from accounts.models import Tenant

    zgloszone = {(wpis.tenant_id, wpis.prog) for wpis in ZgloszonyRozmiar.objects.all()}

    znalezione = []
    firmy = Tenant.objects.annotate(fragmentow=Count("documents__chunks")).filter(
        fragmentow__gte=PROG_UWAGI
    )

    for firma in firmy:
        # Od najwyzszego: firma, ktora od razu przeskoczyla oba progi, ma
        # dostac jedna wiadomosc o tym pilniejszym, a nie dwie.
        for prog in (PROG_PILNY, PROG_UWAGI):
            if firma.fragmentow >= prog and (firma.id, prog) not in zgloszone:
                znalezione.append({"tenant": firma, "prog": prog, "fragmentow": firma.fragmentow})
                break

    return znalezione


def _tresc(znalezione: list[dict]) -> str:
    akapity = [
        "Baza wiedzy klienta rosnie w strone progu, przy ktorym wyszukiwanie "
        "zaczyna byc odczuwalne.",
        "",
    ]

    for wpis in znalezione:
        firma = wpis["tenant"]
        ms = wpis["fragmentow"] * MIKROSEKUND_NA_FRAGMENT / 1000
        pilne = wpis["prog"] == PROG_PILNY

        akapity.append(f"• {firma.name}")
        akapity.append(
            f"  {wpis['fragmentow']:,} fragmentow, czyli okolo {ms:.0f} ms na samo wyszukiwanie."
        )
        if pilne:
            akapity.append(
                f"  To jest kolano krzywej ({PROG_PILNY:,} fragmentow) i zarazem limit planu Start."
            )
            akapity.append(
                "  Powyzej tego miejsca kazde kolejne tysiac fragmentow kosztuje "
                "wiecej niz poprzednie."
            )
        else:
            akapity.append(
                f"  To polowa kolana ({PROG_PILNY:,}). Jeszcze nic sie nie dzieje, "
                "ale jest czas, zeby zdecydowac."
            )
        akapity.append("")

    akapity.append(
        "Co z tym zrobic: docs/adr/001-brak-indeksu-wektorowego.md opisuje opcje "
        "(indeks HNSW, zmiana limitow planow) razem z tym, co kazda kosztuje."
    )
    akapity.append("")
    akapity.append("O tym samym progu u tej samej firmy piszemy raz.")
    return "\n".join(akapity)


def sprawdz_rozmiary() -> int:
    """Zgłasza firmy przy progu. Zwraca liczbę zgłoszeń."""
    from accounts.czuwanie import _adres_operatora

    znalezione = firmy_przy_progu()
    if not znalezione:
        return 0

    pilnych = sum(1 for w in znalezione if w["prog"] == PROG_PILNY)
    temat = (
        f"Baza wiedzy przy progu wydajnosci: {len(znalezione)} "
        f"{'firma' if len(znalezione) == 1 else 'firmy'}"
        + (f", w tym {pilnych} pilnie" if pilnych else "")
    )

    try:
        wyslane = send_mail(
            subject=temat,
            message=_tresc(znalezione),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[_adres_operatora()],
            fail_silently=False,
        )
        if not wyslane:
            raise RuntimeError("send_mail zwrocil 0 - alert nie zostal doreczony")
    except Exception:
        # Znacznika NIE stawiamy przed udana wysylka. Ta sama zasada co przy
        # pozostalych alertach - przy odmowach jej brak kosztowal osobny blad.
        logger.exception("Nie udalo sie wyslac alertu o rozmiarze bazy wiedzy")
        raise

    ZgloszonyRozmiar.objects.bulk_create(
        [
            ZgloszonyRozmiar(
                tenant=wpis["tenant"], prog=wpis["prog"], fragmentow=wpis["fragmentow"]
            )
            for wpis in znalezione
        ]
    )

    logger.warning(
        "Alert o rozmiarze bazy wiedzy: %s",
        ", ".join(f"{w['tenant'].name} ({w['fragmentow']})" for w in znalezione),
    )
    return len(znalezione)


@shared_task
def sprawdz_rozmiary_zadanie():
    """Opakowanie dla Celery."""
    return sprawdz_rozmiary()
