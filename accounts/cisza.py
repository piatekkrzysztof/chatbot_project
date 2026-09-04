"""
Wykrywanie chatbotów, które zamilkły.

Ostatni otwarty punkt z raportu incydentu 26.08.2026:

    „no alert on a drop in conversation volume - which is the signal that
    would have caught this in minutes rather than a day."

Licznik odmów (`accounts/odmowy.py`) widzi awarie, które KTOŚ ODCZUŁ: żeby
powstała odmowa, odwiedzający musi otworzyć czat i nie dostać odpowiedzi.
Jest więc ślepy na całą klasę usterek, przy których widget w ogóle się nie
pojawia - klient przebudował stronę i zgubił nasz fragment, wtyczka do
zarządzania zgodami zablokowała skrypt, certyfikat wygasł, ktoś zmienił
adres. Wtedy nie ma odmów, bo nie ma zapytań. Jest cisza.

Dlaczego zero, a nie spadek procentowy
--------------------------------------
Spadek o połowę wymaga założeń o rozkładzie ruchu i szumi przy każdym
wolniejszym tygodniu. Zero jest jednoznaczne i to właśnie produkuje awaria,
o którą chodzi: widget, którego nie ma na stronie, nie generuje ani jednej
rozmowy.

Cena za tę jednoznaczność: nie wykryjemy spadku z 200 rozmów dziennie do
dziesięciu. To jest świadoma wymiana - alarm, który odzywa się przy każdym
wolniejszym tygodniu, przestaje być czytany, a wtedy przepada także ten
prawdziwy. Dokładnie o tym jest cały tamten raport.

Skąd progi
----------
Alarmujemy tylko dla firm, u których cisza jest NIEPRAWDOPODOBNA. Firma
z ruchem przez 18 z 21 dni odniesienia ma około 14 procent szans na cichy
dzień, czyli około 0,3 procent na trzy ciche dni z rzędu. Firma z ruchem
przez 10 z 21 dni miałaby tych szans około 14 procent - i alarm odzywałby
się co kilka tygodni bez powodu.

Dlatego próg stoi na gęstości ruchu, a nie na jego wielkości. Mały warsztat
z trzema rozmowami dziennie, ale codziennie, jest tu lepszym kandydatem niż
sklep z pięćdziesięcioma rozmowami w poniedziałki i zerem przez resztę
tygodnia.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.db.models.functions import TruncDate
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Ile dni ciszy uznajemy za sygnał.
#:
#: Jeden dzień to za mało: święto, awaria u dostawcy klienta, cokolwiek.
#: Trzy dni to już nie przypadek u firmy, która wcześniej miała ruch prawie
#: codziennie - a jednocześnie na tyle szybko, żeby zdążyć zareagować, zanim
#: klient sam zauważy i zapyta, za co płaci.
OKNO_CISZY = 3

#: Ile dni przed ciszą bierzemy za punkt odniesienia. Trzy pełne tygodnie,
#: żeby cotygodniowy rytm ruchu nie przesuwał wyniku.
OKNO_ODNIESIENIA = 21

#: Ile z tych dni musiało mieć choć jedną rozmowę.
#:
#: 18 z 21 to około 86 procent. Poniżej tego progu cisza przestaje być
#: nieprawdopodobna i alarm zaczyna szumieć - rachunek w opisie modułu.
MINIMUM_DNI_Z_RUCHEM = 18

#: Liczymy wyłącznie rozmowy z widgetu.
#:
#: Rozmowy z panelu to testy właściciela, a te nie mówią nic o tym, czy widget
#: stoi na stronie klienta. Firma, która codziennie klika „Test bota",
#: wyglądałaby na żywą przy zupełnie martwym widgecie.
ZRODLO_WIDGETU = "widget"


class ZgloszonaCisza(models.Model):
    """
    Zapis, że o tej ciszy już powiedzieliśmy.

    Kluczem jest DZIEŃ, w którym cisza się zaczęła, a nie dzień zgłoszenia.
    Dzięki temu trwająca cisza nie odzywa się codziennie: czwartego i piątego
    dnia początek jest wciąż ten sam. Gdy ruch wróci i zamilknie ponownie,
    początek będzie inny i alarm pójdzie na nowo.
    """

    tenant = models.ForeignKey(
        "accounts.Tenant", on_delete=models.CASCADE, related_name="zgloszone_ciszy"
    )
    od_dnia = models.DateField(help_text="Pierwszy dzień bez rozmów")
    zgloszone_dnia = models.DateField(auto_now_add=True)
    dni_ciszy = models.PositiveIntegerField()
    rozmow_przedtem = models.PositiveIntegerField(
        help_text="Ile rozmów firma miała w oknie odniesienia"
    )

    class Meta:
        verbose_name = "Zgłoszona cisza widgetu"
        verbose_name_plural = "Zgłoszone ciszy widgetu"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "od_dnia"], name="unikalna_zgloszona_cisza")
        ]

    def __str__(self):
        return f"{self.tenant.name}: cisza od {self.od_dnia} ({self.dni_ciszy} dni)"


def _dni_z_rozmowami(tenant, od_dnia, do_dnia) -> set:
    """Dni, w których firma miała choć jedną rozmowę z widgetu."""
    from chat.models import Conversation

    return set(
        Conversation.objects.filter(
            tenant=tenant,
            source=ZRODLO_WIDGETU,
            started_at__date__gte=od_dnia,
            started_at__date__lte=do_dnia,
        )
        .annotate(dzien=TruncDate("started_at"))
        .values_list("dzien", flat=True)
        .distinct()
    )


def _poczatek_ciszy(tenant, ostatni_dzien) -> "timezone.datetime.date | None":
    """
    Pierwszy dzień nieprzerwanej ciszy kończącej się `ostatni_dzien`.

    Cofamy się, dopóki dni są puste - dzięki temu wartość nie zmienia się
    z dnia na dzień, gdy cisza trwa, i nadaje się na klucz zgłoszenia.
    Zaglądamy najwyżej w okno odniesienia; dalej i tak nie alarmujemy.
    """
    from chat.models import Conversation

    dzien = ostatni_dzien
    najdalej = ostatni_dzien - timezone.timedelta(days=OKNO_CISZY + OKNO_ODNIESIENIA)

    while dzien > najdalej:
        poprzedni = dzien - timezone.timedelta(days=1)
        byl_ruch = Conversation.objects.filter(
            tenant=tenant,
            source=ZRODLO_WIDGETU,
            started_at__date=poprzedni,
        ).exists()
        if byl_ruch:
            return dzien
        dzien = poprzedni

    return dzien


def firmy_ktore_zamilkly(dzis=None) -> list[dict]:
    """
    Firmy, u których widget przestał generować rozmowy.

    Zwraca listę słowników zamiast obiektów, bo wywołujący potrzebuje też
    liczb z okna odniesienia - a te powstają po drodze i liczenie ich drugi
    raz byłoby zapytaniem o to samo.
    """
    from accounts.models import Tenant
    from chat.models import Conversation

    dzis = dzis or timezone.localdate()

    # Wczoraj, nie dzisiaj: dzisiejszy dzien jeszcze trwa i jego pustka
    # niczego nie znaczy o poranku.
    koniec_ciszy = dzis - timezone.timedelta(days=1)
    poczatek_ciszy = koniec_ciszy - timezone.timedelta(days=OKNO_CISZY - 1)
    koniec_odniesienia = poczatek_ciszy - timezone.timedelta(days=1)
    poczatek_odniesienia = koniec_odniesienia - timezone.timedelta(days=OKNO_ODNIESIENIA - 1)

    znalezione = []

    for tenant in Tenant.objects.all():
        w_ciszy = Conversation.objects.filter(
            tenant=tenant,
            source=ZRODLO_WIDGETU,
            started_at__date__gte=poczatek_ciszy,
            started_at__date__lte=koniec_ciszy,
        ).exists()
        if w_ciszy:
            continue

        dni = _dni_z_rozmowami(tenant, poczatek_odniesienia, koniec_odniesienia)
        if len(dni) < MINIMUM_DNI_Z_RUCHEM:
            # Firma i tak miewa ciche dni - cisza nie jest u niej sygnalem.
            continue

        rozmow = Conversation.objects.filter(
            tenant=tenant,
            source=ZRODLO_WIDGETU,
            started_at__date__gte=poczatek_odniesienia,
            started_at__date__lte=koniec_odniesienia,
        ).count()

        od_dnia = _poczatek_ciszy(tenant, poczatek_ciszy)

        znalezione.append(
            {
                "tenant": tenant,
                "od_dnia": od_dnia,
                "dni_ciszy": (koniec_ciszy - od_dnia).days + 1,
                "dni_z_ruchem": len(dni),
                "rozmow_przedtem": rozmow,
            }
        )

    return znalezione


def _tresc(znalezione: list[dict]) -> str:
    akapity = [
        "Widget przestał generować rozmowy u firm, u których wcześniej "
        "generował je prawie codziennie.",
        "",
        "To zwykle nie jest awaria po naszej stronie - częściej fragment "
        "zniknął ze strony klienta przy przebudowie albo zablokowała go "
        "wtyczka zgód. Warto otworzyć stronę klienta i sprawdzić, czy "
        "bąbelek czatu się pojawia.",
        "",
    ]

    for wpis in znalezione:
        akapity.append(f"• {wpis['tenant'].name}")
        akapity.append(f"  Cisza od {wpis['od_dnia']}, czyli {wpis['dni_ciszy']} dni.")
        akapity.append(
            f"  Wcześniej: {wpis['rozmow_przedtem']} rozmów przez "
            f"{wpis['dni_z_ruchem']} z {OKNO_ODNIESIENIA} dni."
        )
        akapity.append("")

    akapity.append(
        "O tej samej ciszy piszemy raz. Jeśli ruch wróci i zamilknie ponownie, "
        "dostaniesz nową wiadomość."
    )
    return "\n".join(akapity)


def sprawdz_cisze(dzis=None) -> int:
    """
    Zgłasza firmy, u których widget zamilkł. Zwraca liczbę zgłoszeń.

    Uruchamiane raz na dobę - sygnał jest z natury dobowy, więc częstsze
    sprawdzanie powtarzałoby tę samą odpowiedź.
    """
    from accounts.czuwanie import _adres_operatora

    dzis = dzis or timezone.localdate()

    nowe = [
        wpis
        for wpis in firmy_ktore_zamilkly(dzis)
        if not ZgloszonaCisza.objects.filter(
            tenant=wpis["tenant"], od_dnia=wpis["od_dnia"]
        ).exists()
    ]

    if not nowe:
        return 0

    try:
        wyslane = send_mail(
            subject=f"Chatbot zamilkł: {len(nowe)} {'firma' if len(nowe) == 1 else 'firmy'}",
            message=_tresc(nowe),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[_adres_operatora()],
            fail_silently=False,
        )
        if not wyslane:
            raise RuntimeError("send_mail zwrocil 0 - alert nie zostal doreczony")
    except Exception:
        # Znacznika NIE stawiamy: nieudana wysyłka nie może uchodzić za
        # doręczoną. Ta sama zasada co przy alercie o odmowach - tam kosztowała
        # osobny błąd, znaleziony dopiero przez CI.
        logger.exception("Nie udalo sie wyslac alertu o ciszy widgetu")
        raise

    ZgloszonaCisza.objects.bulk_create(
        [
            ZgloszonaCisza(
                tenant=wpis["tenant"],
                od_dnia=wpis["od_dnia"],
                dni_ciszy=wpis["dni_ciszy"],
                rozmow_przedtem=wpis["rozmow_przedtem"],
            )
            for wpis in nowe
        ]
    )

    logger.warning(
        "Alert o ciszy widgetu wyslany: %s",
        ", ".join(wpis["tenant"].name for wpis in nowe),
    )
    return len(nowe)


@shared_task
def sprawdz_cisze_zadanie():
    """
    Opakowanie dla Celery.

    Samo `sprawdz_cisze` przyjmuje datę, żeby dało się je uruchomić dla
    dowolnego dnia w teście. Zadanie w harmonogramie nie ma czego przyjmować.
    """
    return sprawdz_cisze()
