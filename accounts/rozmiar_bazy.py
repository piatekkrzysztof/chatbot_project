"""
Ostrzeżenie, gdy baza wiedzy klienta zbliża się do progu wydajności.

Skąd to się wzięło
------------------
Pomiar na produkcji ([docs/skala-i-wydajnosc.md]) pokazał, że wyszukiwanie
rośnie gorzej niż liniowo. Do tej pory jedynym sposobem, żeby się o tym
dowiedzieć, było uruchomienie komendy pomiarowej i pamiętanie, żeby to zrobić.
`docs/adr/001` nazywa ten brak wprost: „można to obserwować, zamiast na to
czekać, a alertu nie ma".

Dlaczego dwa progi, a nie jeden
-------------------------------
Jeden próg odpowiada tylko na pytanie „czy już". Dwa odpowiadają też na „ile
zostało czasu", a to jest różnica między informacją a wezwaniem.

  • 15 000 fragmentów - wyszukiwanie przekracza pół sekundy (537 ms). Nic się
    jeszcze nie psuje, ale klient rośnie i jest czas, żeby spokojnie
    zdecydować, co dalej.
  • 25 000 fragmentów - sekunda, kolano krzywej i limit planu Grow naraz.
    W tym miejscu tabela przestaje mieścić się w pamięci instancji, więc każdy
    kolejny fragment kosztuje dwa razy więcej niż poniżej.

Progi są liczone z czasu, jaki czuje odwiedzający, a nie z liczby wierszy.
Poprzednia para (2 500 i 5 000) pochodziła z kolana sprzed skrócenia wektora
do 512 wymiarów; po tamtej zmianie odpowiadała 60 i 120 ms, czyli alarmowała
pięciokrotnie za wcześnie.

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

#: Krzywa wyszukiwania zmierzona na produkcji 8 września 2026, 512 wymiarów.
#: `manage.py zmierz_skale --do 40000`, szczegóły w docs/skala-i-wydajnosc.md.
#:
#: Punkty, nie współczynnik, bo krzywa NIE jest prostą. Do 10 000 fragmentów
#: tabela mieści się w pamięci instancji i fragment kosztuje 23 µs; od około
#: 25 000 zapytanie czyta z dysku całą tabelę i fragment kosztuje 53 µs.
#: Jeden współczynnik zaniżałby albo górę, albo dół - a poprzednia wersja tego
#: modułu miała właśnie taki (88 µs) i opisywała nim świat sprzed migracji.
KRZYWA_MS = ((1_000, 9), (5_000, 188), (10_000, 305), (25_000, 1_001), (40_000, 1_802))


def milisekundy(fragmentow: int) -> float:
    """
    Ile trwa wyszukiwanie przy tylu fragmentach, wprost ze zmierzonych punktów.

    Interpolacja liniowa między nimi, a powyżej ostatniego - przedłużenie
    ostatniego odcinka. To ostatnie jest ekstrapolacją i zaniża, bo nachylenie
    krzywej wciąż rosło; wiadomość o firmie powyżej 40 000 fragmentów poda
    więc czas mniejszy niż rzeczywisty. Lepiej to niż liczba wzięta znikąd.
    """
    if fragmentow <= KRZYWA_MS[0][0]:
        return fragmentow * KRZYWA_MS[0][1] / KRZYWA_MS[0][0]

    for (a, ta), (b, tb) in zip(KRZYWA_MS, KRZYWA_MS[1:], strict=False):
        if a <= fragmentow <= b:
            return ta + (tb - ta) * (fragmentow - a) / (b - a)

    (przed, t_przed), (ostatni, t_ostatni) = KRZYWA_MS[-2], KRZYWA_MS[-1]
    tempo = (t_ostatni - t_przed) / (ostatni - przed)
    return t_ostatni + (fragmentow - ostatni) * tempo


#: Pierwszy próg: wyszukiwanie przekracza pół sekundy.
#:
#: 15 000 fragmentów to około 540 ms - tyle, ile trwa zauważalna pauza, zanim
#: model w ogóle zacznie pisać. Nic się jeszcze nie psuje, ale od tego miejsca
#: warto wiedzieć, że klient rośnie.
PROG_UWAGI = 15_000

#: Drugi próg: wyszukiwanie przekracza sekundę, i to nie przez przypadek.
#:
#: Przy 25 000 fragmentów (69 MB) tabela przestaje mieścić się w pamięci
#: podręcznej instancji: przy 40 000 zapytanie czyta z dysku 110 MB, czyli
#: całą tabelę, przy KAŻDYM pytaniu. Koszt fragmentu podwaja się z 23 na 53 µs.
#: To jest dzisiejsze kolano krzywej i zarazem limit planu Grow.
PROG_PILNY = 25_000

#: Poprzednie wartości: 2 500 i 5 000, dobrane pod kolano sprzed skrócenia
#: wektora do 512 wymiarów. Po migracji odpowiadały 60 i 120 ms - alarmowały
#: pięć razy za wcześnie. Zostawione świadomie do czasu tego pomiaru, bo
#: pomyłka w tę stronę kosztuje zbędny mail, a w drugą wolnego bota.


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
        ms = milisekundy(wpis["fragmentow"])
        pilne = wpis["prog"] == PROG_PILNY

        akapity.append(f"• {firma.name}")
        akapity.append(
            f"  {wpis['fragmentow']:,} fragmentow, czyli okolo {ms:.0f} ms na samo wyszukiwanie."
        )
        if pilne:
            akapity.append(
                f"  To jest kolano krzywej ({PROG_PILNY:,} fragmentow) i zarazem limit planu Grow."
            )
            akapity.append(
                "  W tym miejscu tabela przestaje miescic sie w pamieci instancji, "
                "wiec zapytanie zaczyna czytac ja z dysku - i kazdy kolejny "
                "fragment kosztuje dwa razy wiecej niz ponizej tego progu."
            )
        else:
            akapity.append(
                f"  Kolano krzywej jest przy {PROG_PILNY:,}. Jeszcze nic sie nie dzieje, "
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
