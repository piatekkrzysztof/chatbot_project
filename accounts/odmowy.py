"""
Ślad po odmowach obsługi widgetu.

Raport z incydentu 26.08.2026 zawiera zdanie, które jest tu punktem wyjścia:
„We cannot count what we did not log". Chatbot jednego klienta milczał przez
dobę, a my do dziś nie wiemy, ilu odwiedzających dostało wtedy komunikat
o błędzie - bo `SubscriptionMiddleware` odmawia przed wejściem do widoku
i nie zapisuje niczego.

Zliczenia, nie zdarzenia
------------------------
Jeden wiersz na odmowę byłby prostszy, ale widget na ruchliwej stronie
z wygasłą subskrypcją potrafi zebrać dziesiątki tysięcy odmów dziennie -
i to akurat wtedy, gdy baza ma najmniej powodów, żeby puchnąć. Do alertu
i do odpowiedzi na pytanie „ilu ludzi to dotknęło" wystarczą liczby.
Jeden wiersz na firmę, powód i dzień jest ograniczony z góry i tani.

To nie jest dziennik audytowy
-----------------------------
`WpisDziennika` zapisuje działania ludzi w panelu i celowo pomija `/api/widget/`
- ruch odwiedzających utopiłby w nim to, po co się dziennik czyta. Tutaj jest
odwrotnie: liczy się wyłącznie ruch widgetu, i to tylko ten odrzucony.
"""

from django.db import IntegrityError, models
from django.db.models import F
from django.utils import timezone


class PowodOdmowy(models.TextChoices):
    """
    Powody rozdzielone drobniej niż widzi je odwiedzający.

    Na zewnątrz wszystkie te odmowy niosą jeden kod `czat_niedostepny`, bo
    rozliczenia klienta nie są sprawą jego odwiedzających. Wewnątrz muszą być
    rozróżnialne: wygasła subskrypcja to sprawa dla nas, a wyczerpany limit
    wiadomości to sprawa właściciela, który dostaje o nim własne maile.
    """

    BRAK_KLUCZA = "brak_klucza", "Żądanie bez klucza API"
    ZLY_KLUCZ = "zly_klucz", "Nieznany klucz API"
    BRAK_SUBSKRYPCJI = "brak_subskrypcji", "Firma bez subskrypcji"
    BRAK_AKTYWNEJ = "brak_aktywnej", "Żadna subskrypcja nie jest aktywna"
    SUBSKRYPCJA_WYGASLA = "subskrypcja_wygasla", "Subskrypcja poza datami ważności"
    LIMIT_WIADOMOSCI = "limit_wiadomosci", "Wyczerpany limit wiadomości"


#: Powody, o których ma się dowiedzieć operator, a nie właściciel.
#:
#: `LIMIT_WIADOMOSCI` jest poza tym zbiorem świadomie: właściciel dostaje o nim
#: maile przy 80, 95 i 100 procentach zużycia, a wyczerpanie limitu jest
#: normalnym końcem cyklu, nie awarią. Alarmowanie o nim zamieniłoby
#: powiadomienia w szum, przez który przestałoby się widzieć te ważne.
POWODY_ALARMUJACE = frozenset(
    {
        PowodOdmowy.BRAK_SUBSKRYPCJI,
        PowodOdmowy.BRAK_AKTYWNEJ,
        PowodOdmowy.SUBSKRYPCJA_WYGASLA,
    }
)


class ZliczenieOdmow(models.Model):
    """Ile razy widget odmówił obsługi: firma, powód, dzień."""

    #: Puste przy nieznanym albo brakującym kluczu API - wtedy nie ma czego
    #: przypisać. Takie wiersze mówią o czymś innym niż awaria u klienta:
    #: o źle wklejonym fragmencie na czyjejś stronie albo o kimś, kto obmacuje
    #: nasze API. Jedno i drugie warto widzieć.
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="odmowy_widgetu",
    )

    powod = models.CharField(max_length=32, choices=PowodOdmowy.choices)

    #: Data w strefie serwera. Doba jest wystarczającą rozdzielczością do
    #: pytania „ile" i do decyzji „czy to nowa awaria".
    dzien = models.DateField()

    liczba = models.PositiveIntegerField(default=0)

    #: Godziny pierwszej i ostatniej odmowy tego dnia. Bez nich wiadomo, że
    #: awaria trwała, ale nie wiadomo, od kiedy - a przy incydencie to jest
    #: pierwsze pytanie.
    pierwsza = models.DateTimeField()
    ostatnia = models.DateTimeField()

    #: Czy operator dostal juz o tym wiadomosc.
    #:
    #: Granulacja jest taka sama jak wiersza - firma, powod, dzien - i to jest
    #: cala regula ponawiania: trwajaca awaria nie alarmuje co godzine, ale
    #: nastepnego dnia zaklada nowy wiersz i przypomina o sobie raz. Chatbot
    #: milczacy siodmy dzien ma sie odezwac siodmy raz, a nie zamilknac takze
    #: w powiadomieniach.
    zgloszone = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Zliczenie odmów widgetu"
        verbose_name_plural = "Zliczenia odmów widgetu"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "powod", "dzien"],
                name="unikalne_zliczenie_odmow",
            )
        ]
        indexes = [models.Index(fields=["dzien", "powod"])]

    def __str__(self):
        firma = self.tenant.name if self.tenant else "bez firmy"
        return f"{firma} / {self.get_powod_display()} / {self.dzien}: {self.liczba}"


def zapisz_odmowe(tenant, powod):
    """
    Podbija licznik odmów o jeden.

    Bez blokad i bez `select_for_update`: najpierw UPDATE, a INSERT dopiero
    wtedy, gdy nie było czego podbić. Dwa równoległe żądania mogą trafić na tę
    samą lukę między UPDATE a INSERT - drugie dostanie wtedy IntegrityError
    z ograniczenia unikalności i po prostu podbije wiersz utworzony przez
    pierwsze.

    Wywoływane z middleware, w ścieżce każdego odrzuconego żądania widgetu,
    więc musi być tanie: jedno zapytanie w zwykłym przypadku.
    """
    teraz = timezone.now()
    dzien = timezone.localdate(teraz)

    wiersze = ZliczenieOdmow.objects.filter(tenant=tenant, powod=powod, dzien=dzien)

    if wiersze.update(liczba=F("liczba") + 1, ostatnia=teraz):
        return

    try:
        ZliczenieOdmow.objects.create(
            tenant=tenant,
            powod=powod,
            dzien=dzien,
            liczba=1,
            pierwsza=teraz,
            ostatnia=teraz,
        )
    except IntegrityError:
        # Wyścig: ktoś utworzył ten wiersz między naszym UPDATE a INSERT.
        wiersze.update(liczba=F("liczba") + 1, ostatnia=teraz)
