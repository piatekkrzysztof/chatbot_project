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
    python manage.py zmierz_skale --do 40000
"""

import random
import statistics
import time

from django.core.management.base import BaseCommand
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


class Command(BaseCommand):
    help = "Mierzy, jak czas wyszukiwania rosnie z wielkoscia bazy wiedzy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--do",
            type=int,
            default=max(PROGI),
            metavar="N",
            help="Najwiekszy mierzony rozmiar bazy wiedzy (domyslnie 85000).",
        )

    def handle(self, *args, **opcje):
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
        self.stdout.write(
            "Czas rosnie z liczba fragmentow TEJ firmy. Dane innych firm nie maja\n"
            "znaczenia - sprawdzone osobno: maly klient ma te sama odpowiedz obok\n"
            "pustej bazy i obok 40 tysiecy cudzych fragmentow.\n"
            "\n"
            "Kolumna 'fragmentow' zestawiona z cennikiem wyzej mowi, ktory plan\n"
            "sprzedaje baze wiedzy wieksza, niz obsluzymy szybko."
        )
