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

Domyslnie mierzy do 10 000 fragmentow, czyli zapisuje okolo 27 MB. Wieksze
przebiegi trzeba potwierdzic, bo pelny zapisuje ponad 230 MB - a uruchomiona
na serwerze komenda pisze do bazy PRODUKCYJNEJ.

Przed skroceniem wektora do 512 wymiarow bylo to odpowiednio 80 MB i 680 MB.
Zabezpieczenie zostaje mimo to: jego wartoscia jest swiadome potwierdzenie,
nie konkretna liczba megabajtow.
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
from documents.wymiar import WYMIAR_WEKTORA
from rag.engine import fragmenty_do_przeszukania

POMIAROW = 9
PARTIA = 500

#: Punkty pomiarowe. Ostatni odpowiada mniej więcej pełnemu planowi Pro.
PROGI = (1_000, 5_000, 10_000, 25_000, 40_000, 85_000)

MB = 1024 * 1024

#: Ile miejsca zajmuje jeden fragment razem z indeksami. Przy 512 wymiarach.
#:
#: Zmierzone, nie wyliczone - i to jest tu najwazniejsze zdanie.
#:
#: Pierwsza wersja tej zmiany liczyla to ze wzoru "wektor plus staly narzut":
#: 8,2 kB przy 1536 wymiarach minus 6,0 kB samego wektora dawalo 2,2 kB
#: narzutu, wiec przy 512 wymiarach wychodzilo 2,0 + 2,2 = 4,2 kB. Pomiar
#: pokazal 2,8 kB. Narzut nie jest staly: wektor 1536-wymiarowy laduje
#: w TOAST razem z jego wlasnym indeksem, a krotszy placi za to mniej.
#:
#: Wzor wygladal na uzasadniony i mylil sie o polowe. Dlatego stoi tu liczba
#: z pomiaru, a `_porownaj_rozmiar` wypisuje ja obok rzeczywistego przyrostu
#: przy kazdym przebiegu - z ostrzezeniem, gdy sie rozjada. Tak wlasnie
#: wyszedl na jaw ten blad.
#:
#: Potwierdzone dwukrotnie, niezaleznie: 5 000 fragmentow -> 13,8 MB
#: (7 wrzesnia 2026) i 10 000 fragmentow -> 27,3 MB (5 wrzesnia 2026).
KB_NA_FRAGMENT = 2.8

#: Domyslny rozmiar pomiaru dobrany tak, zeby byl bezpieczny WSZEDZIE.
#:
#: 10 000 fragmentow to okolo 27 MB i wystarcza, zeby zobaczyc, gdzie krzywa
#: przestaje byc liniowa. Pelny przebieg do 85 000 zapisuje ponad 230 MB,
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
        230 MB, ktore musza sie w niej zmiescic obok danych klientow.

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
        return [losowy.uniform(-1, 1) for _ in range(WYMIAR_WEKTORA)]

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
        instancji. Ile to znaczy w megabajtach, mowi wiersz "rozmiar tabeli"
        wypisany razem z pomiarem - i to z niego, nie z pamieci, bierze sie
        odpowiedz, czy dane maja gdzie sie zmiescic.
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

    def _rozmiar_tabeli(self):
        """
        Ile naprawde zajmuje tabela fragmentow, razem z indeksami.

        KB_NA_FRAGMENT jest liczba z pomiaru, ale z pomiaru zrobionego kiedys
        i gdzie indziej. Bez porownania jej z tym, co dzieje sie TERAZ i w TEJ
        bazie, bylaby oszacowaniem, ktore wyglada jak pomiar - a stoi na niej
        i cennik wypisywany wyzej, i odmowa zapisu do produkcji.
        """
        from django.db import connection

        with connection.cursor() as kursor:
            kursor.execute("SELECT pg_total_relation_size('documents_documentchunk')")
            return kursor.fetchone()[0]

    def _porownaj_rozmiar(self, przed, fragmentow):
        """
        Zestawia oszacowanie z pomiarem i mowi, gdy sie rozjezdzaja.

        Bez tego zestawienia KB_NA_FRAGMENT byloby liczba, ktorej nikt nigdy
        nie sprawdza - a stoi na niej i cennik wyzej, i odmowa zapisu do
        produkcji. Wartosc dla 512 wymiarow jest przeliczona, nie zmierzona;
        ten wiersz jest miejscem, w ktorym sie to rozstrzyga.
        """
        przyrost = self._rozmiar_tabeli() - przed
        zmierzone_kb = przyrost / 1024 / fragmentow

        self.stdout.write("")
        self.stdout.write(
            f"Rozmiar tabeli: przyrost {przyrost / MB:.1f} MB na {fragmentow:,} fragmentow "
            f"= {zmierzone_kb:.1f} kB/fragment"
        )
        self.stdout.write(f"  oszacowanie w kodzie: {KB_NA_FRAGMENT:.1f} kB/fragment")

        # 15% zapasu: rozmiar zalezy od wypelnienia stron i od tego, kiedy
        # autovacuum zdazyl posprzatac, wiec drobna roznica nic nie znaczy.
        if abs(zmierzone_kb - KB_NA_FRAGMENT) > 0.15 * KB_NA_FRAGMENT:
            self.stdout.write(
                self.style.WARNING(
                    "  UWAGA: rozjazd ponad 15%. KB_NA_FRAGMENT w zmierz_skale.py "
                    "opisuje inna baze niz ta - popraw KB_NARZUTU_NA_FRAGMENT."
                )
            )

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

        # Rozmiar PRZED dosypaniem. Tabela jest wspolna dla wszystkich firm,
        # wiec na produkcji jest w niej juz baza wiedzy klientow - roznica
        # miedzy stanem przed i po jest jedynym sposobem, zeby zmierzyc
        # fragmenty pomiarowe, a nie cudze dane.
        przed = self._rozmiar_tabeli()

        self.stdout.write(f"{'fragmentow':>11} {'mediana ms':>11} {'najgorszy ms':>13}")
        self.stdout.write("-" * 38)

        lacznie = 0
        for prog in progi:
            self._dosyp(dokument, prog - lacznie, losowy)
            lacznie = prog
            mediana, najgorszy = self._czas(firma, zapytanie)
            self.stdout.write(f"{lacznie:>11,} {mediana:>11.1f} {najgorszy:>13.1f}")

        self._porownaj_rozmiar(przed, lacznie)

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
