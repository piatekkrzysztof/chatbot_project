"""
Ile kosztuje wyszukiwanie przy rosnącej bazie wiedzy.

Pytanie, na które odpowiada: ilu klientów i jak dużych uniesiemy, zanim bot
zacznie odpowiadać wolno. Do tej pory nie było na nie odpowiedzi - ani liczby,
ani sposobu jej zdobycia.

Czego ta komenda NIE mierzy
---------------------------
Przepustowości w żądaniach na sekundę. Ta zależy od maszyny, a numer z laptopa
deweloperskiego nic nie mówi o instancji na Renderze - wyglądałby na wynik
i nim nie był.

Mierzymy zamiast tego KSZTAŁT: jak czas wyszukiwania rośnie z liczbą
fragmentów. To jest własność zapytania i braku indeksu, nie procesora.
Uruchomiona na serwerze da inne liczby bezwzględne, ale ten sam kształt -
i dlatego warto ją tam uruchomić.

Co jest tworzone i kasowane
---------------------------
Komenda zakłada tymczasową firmę z losowymi wektorami i kasuje ją na końcu,
także gdy pomiar przerwie błąd. Wektory są losowe świadomie: koszt liczenia
odległości nie zależy od wartości, a policzenie stu tysięcy prawdziwych
kosztowałoby realne pieniądze i nic by nie wniosło.

    python manage.py zmierz_skale
    python manage.py zmierz_skale --do 85000 --wiem-ze-pisze-do-tej-bazy

Domyslnie mierzy do 10 000 fragmentow, czyli zapisuje okolo 80 MB. Wieksze
przebiegi trzeba potwierdzic, bo pelny zapisuje ponad 680 MB - a uruchomiona
na serwerze komenda pisze do bazy PRODUKCYJNEJ.
"""

import random
import statistics
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from pgvector.django import L2Distance

from accounts.models import Tenant
from accounts.plans import PLANS
from documents.models import Document, DocumentChunk
from documents.utils.fragmenty import MAKS_ZNAKOW, ZAKLADKA
from rag.engine import fragmenty_do_przeszukania

WYMIAR = 1536
POMIAROW = 9
PARTIA = 500

#: Punkty pomiarowe. Ostatni odpowiada mniej więcej pełnemu planowi Pro.
PROGI = (1_000, 5_000, 10_000, 25_000, 40_000, 85_000)

MB = 1024 * 1024

#: Ile miejsca zajmuje jeden fragment razem z indeksami.
#:
#: Zmierzone 4 wrzesnia 2026 na PostgreSQL 16: 5 000 fragmentow zajelo 40,1 MB,
#: czyli 8,2 kB na sztuke. Wektor to 1536 liczb po 4 bajty, wiec sam zajmuje
#: 6 kB - reszta to naglowki wiersza i indeksy.
KB_NA_FRAGMENT = 8.2

#: Domyslny rozmiar pomiaru dobrany tak, zeby byl bezpieczny WSZEDZIE.
#:
#: 10 000 fragmentow to okolo 80 MB i wystarcza, zeby zobaczyc, gdzie krzywa
#: przestaje byc liniowa. Pelny przebieg do 85 000 zapisuje ponad 680 MB -
#: na malej instancji hostingu to rozmiar, ktory potrafi zapelnic dysk bazy,
#: a komenda uruchomiona na serwerze pisze do bazy PRODUKCYJNEJ.
#:
#: Pierwsza wersja tej komendy miala 85 000 jako domyslne i nie mowila o tym
#: ani slowa. Bylaby to pulapka zastawiona na kogos, kto zaufa narzedziu.
DOMYSLNY_ROZMIAR = 10_000

#: Powyzej tego progu trzeba potwierdzic swiadomie.
PROG_POTWIERDZENIA = 25_000


class Command(BaseCommand):
    help = "Mierzy, jak czas wyszukiwania rosnie z wielkoscia bazy wiedzy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--do",
            type=int,
            default=DOMYSLNY_ROZMIAR,
            metavar="N",
            help=f"Najwiekszy mierzony rozmiar bazy wiedzy (domyslnie {DOMYSLNY_ROZMIAR}).",
        )
        parser.add_argument(
            "--wiem-ze-pisze-do-tej-bazy",
            action="store_true",
            help=(
                f"Wymagane powyzej {PROG_POTWIERDZENIA} fragmentow. Pomiar zapisuje "
                "dane do bazy, z ktora jest polaczony - na serwerze to baza produkcyjna."
            ),
        )

    def handle(self, *args, **opcje):
        self._ostrzez(opcje["do"], opcje["wiem_ze_pisze_do_tej_bazy"])
        self._cennik()

        losowy = random.Random(20260904)
        firma = None
        try:
            firma, dokument = self._zaloz(losowy)
            self._mierz(firma, dokument, losowy, opcje["do"])
        finally:
            if firma is not None:
                # Kasujemy takze po bledzie - inaczej przerwany pomiar
                # zostawialby w bazie firme ze stu tysiacami wierszy.
                firma.delete()
                self.stdout.write("")
                self.stdout.write("Dane pomiarowe usuniete.")

    def _ostrzez(self, maksimum, potwierdzone):
        """
        Mowi, ile miejsca zajmie pomiar, i nie pozwala go zrobic na slepo.

        Komenda zapisuje fragmenty do bazy, z ktora jest polaczona. Uruchomiona
        na serwerze pisze do bazy PRODUKCYJNEJ - a pelny przebieg to ponad
        680 MB, czyli rozmiar zdolny zapelnic dysk malej instancji.

        Dane sa kasowane na koncu, takze po bledzie, ale w trakcie musza sie
        gdzies zmiescic.
        """
        megabajty = maksimum * KB_NA_FRAGMENT / 1024
        baza = settings.DATABASES["default"]

        self.stdout.write(
            f"Pomiar zapisze do {maksimum:,} fragmentow, czyli okolo {megabajty:.0f} MB, do bazy:"
        )
        self.stdout.write(f"  {baza.get('NAME')} na {baza.get('HOST') or 'localhost'}")
        self.stdout.write("Dane sa kasowane na koncu, takze po bledzie.")
        self.stdout.write("")

        if maksimum > PROG_POTWIERDZENIA and not potwierdzone:
            raise CommandError(
                "\n".join(
                    [
                        f"{maksimum:,} fragmentow to okolo {megabajty:.0f} MB "
                        f"zapisane do bazy '{baza.get('NAME')}'.",
                        "Na serwerze jest to baza produkcyjna i tyle miejsca musi",
                        "sie w niej zmiescic na czas pomiaru.",
                        "",
                        "Jesli o tym wiesz, dodaj --wiem-ze-pisze-do-tej-bazy.",
                        "Jesli chcesz tylko zobaczyc ksztalt krzywej, zostaw "
                        f"domyslne {DOMYSLNY_ROZMIAR:,} (okolo "
                        f"{DOMYSLNY_ROZMIAR * KB_NA_FRAGMENT / 1024:.0f} MB).",
                    ]
                )
            )

    def _cennik(self):
        """Ile fragmentów mieści się w limicie każdego planu."""
        krok = MAKS_ZNAKOW - ZAKLADKA
        self.stdout.write(
            f"Fragment: do {MAKS_ZNAKOW} znakow, zakladka {ZAKLADKA} -> krok {krok} znakow"
        )
        self.stdout.write("")
        self.stdout.write(f"{'plan':>6} {'limit MB':>9} {'fragmentow ~':>13}")
        for kod, plan in PLANS.items():
            self.stdout.write(
                f"{kod:>6} {plan.knowledge_base_mb:>9} {plan.knowledge_base_mb * MB // krok:>13,}"
            )
        self.stdout.write("")

    def _wektor(self, losowy):
        return [losowy.uniform(-1, 1) for _ in range(WYMIAR)]

    @transaction.atomic
    def _zaloz(self, losowy):
        firma = Tenant.objects.create(name="Pomiar skali (tymczasowa)")
        dokument = Document.objects.create(
            tenant=firma,
            name="Baza pomiarowa",
            content="pomiar",
            # processed=False, zeby nie odpalic sygnalu generowania wektorow.
            processed=False,
        )
        return firma, dokument

    def _dosyp(self, dokument, ile, losowy):
        partia = []
        for numer in range(ile):
            partia.append(
                DocumentChunk(
                    document=dokument,
                    content=f"fragment {numer}",
                    embedding=self._wektor(losowy),
                )
            )
            if len(partia) >= PARTIA:
                DocumentChunk.objects.bulk_create(partia)
                partia = []
        if partia:
            DocumentChunk.objects.bulk_create(partia)

    def _plan(self, firma, zapytanie):
        """
        Skad bierze sie czas: z procesora czy z dysku.

        Sam pomiar mowi, ze jest wolno, i nie mowi dlaczego. A od tego zalezy,
        co z tym zrobic: wiekszy RAM przesuwa sufit tylko wtedy, gdy zapytanie
        czyta z dysku, bo tabela przestala sie miescic w pamieci podrecznej.
        Jesli wszystko przychodzi z pamieci, a mimo to trwa - waskim gardlem
        jest procesor i wieksza baza nic nie da.

        Liczniki blokow odpowiadaja na to wprost:
          shared hit  - przeczytane z pamieci podrecznej,
          shared read - przeczytane z dysku.

        Postgres trzyma w pamieci podrecznej okolo jednej czwartej RAM-u
        instancji. Fragment zajmuje 8,2 kB, wiec 10 000 fragmentow to 82 MB -
        na malej instancji to jest wiecej, niz sie tam miesci.
        """
        from django.db import connection

        with connection.cursor() as kursor:
            kursor.execute(
                """
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT dc.id
                FROM documents_documentchunk dc
                JOIN documents_document d ON d.id = dc.document_id
                WHERE d.tenant_id = %s AND d.uzywaj_w_wyszukiwaniu
                ORDER BY dc.embedding <-> %s::vector
                LIMIT 5
                """,
                [firma.id, str(zapytanie)],
            )
            return [wiersz[0] for wiersz in kursor.fetchall()]

    def _czas(self, firma, zapytanie):
        czasy = []
        for _ in range(POMIAROW):
            start = time.perf_counter()
            list(
                fragmenty_do_przeszukania(firma.id)
                .annotate(distance=L2Distance("embedding", zapytanie))
                .filter(distance__lte=1.0)
                .order_by("distance")[:5]
            )
            czasy.append((time.perf_counter() - start) * 1000)
        return statistics.median(czasy), max(czasy)

    def _mierz(self, firma, dokument, losowy, maksimum):
        zapytanie = self._wektor(losowy)
        progi = [p for p in PROGI if p <= maksimum]

        self.stdout.write(f"{'fragmentow':>11} {'mediana ms':>11} {'najgorszy ms':>13}")
        self.stdout.write("-" * 38)

        lacznie = 0
        for prog in progi:
            self._dosyp(dokument, prog - lacznie, losowy)
            lacznie = prog
            mediana, najgorszy = self._czas(firma, zapytanie)
            self.stdout.write(f"{lacznie:>11,} {mediana:>11.1f} {najgorszy:>13.1f}")

        self.stdout.write("")
        self.stdout.write(f"Plan zapytania przy {lacznie:,} fragmentach:")
        for wiersz in self._plan(firma, zapytanie):
            self.stdout.write("  " + wiersz)

        self.stdout.write("")
        self.stdout.write("Jak to czytac:")
        self.stdout.write("  'shared hit'  - bloki przeczytane z pamieci podrecznej bazy,")
        self.stdout.write("  'shared read' - bloki przeczytane z dysku.")
        self.stdout.write("")
        self.stdout.write("  Duzo 'read' znaczy, ze tabela przestala sie miescic w pamieci.")
        self.stdout.write("  Wtedy wiekszy RAM instancji przesunie sufit, i to mniej wiecej")
        self.stdout.write("  proporcjonalnie.")
        self.stdout.write("")
        self.stdout.write("  Same 'hit' przy dlugim czasie znacza cos innego: waskim gardlem")
        self.stdout.write("  jest procesor, a wieksza baza danych nie da nic poza rachunkiem.")

        self.stdout.write("")
        self.stdout.write(
            "Czas rosnie z liczba fragmentow TEJ firmy. Dane innych firm nie maja\n"
            "znaczenia - sprawdzone osobno: maly klient ma te sama odpowiedz obok\n"
            "pustej bazy i obok 40 tysiecy cudzych fragmentow.\n"
            "\n"
            "Kolumna 'fragmentow' zestawiona z cennikiem wyzej mowi, ktory plan\n"
            "sprzedaje baze wiedzy wieksza, niz obsluzymy szybko."
        )
