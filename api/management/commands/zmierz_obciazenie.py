"""
Ile żądań na sekundę wytrzymuje API, zanim przestanie mieścić się w SLO.

Pytanie, na które odpowiada: przy jakim ruchu progi z docs/slo-i-czasy-odpowiedzi.md
jeszcze się trzymają. `zmierz_skale` mówi, jak rośnie samo wyszukiwanie wektorowe;
ta komenda mierzy całą drogę żądania przez gunicorna, middleware i bazę.

Czego ta komenda NIE robi
-------------------------
Nie dotyka czatu ani strumienia odpowiedzi - te płacą tokenami OpenAI za każde
wywołanie, więc scenariusz rozmowy uruchamia się osobno i po decyzji właściciela
(patrz docs/test-obciazeniowy.md). Tutaj są wyłącznie ścieżki, które nic nie
kosztują: ustawienia widgetu, publiczne FAQ i listy panelu.

Nie zastępuje też k6 na produkcji. Liczby z laptopa nie przenoszą się na
instancję Rendera; przenosi się kształt i miejsce, w którym coś puszcza.

Biblioteka standardowa, bez nowych zależności - narzędzie pomiarowe nie może
kosztować zależności w obrazie produkcyjnym.

    python manage.py zmierz_obciazenie --adres http://localhost:8000 --klucz UUID
    python manage.py zmierz_obciazenie --klucz UUID --token JWT --rps 8 --czas 60
"""

import statistics
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

#: Progi z SLO (docs/slo-i-czasy-odpowiedzi.md), w milisekundach.
PROGI_P95 = {"widget": 500, "panel": 800}

#: Dopuszczalny udział odpowiedzi 5xx.
PROG_BLEDOW = 0.005


class Scenariusz:
    """Jedno żądanie w profilu ruchu: ścieżka, waga i obszar progu SLO."""

    def __init__(self, nazwa, sciezka, waga, obszar, naglowki):
        self.nazwa = nazwa
        self.sciezka = sciezka
        self.waga = waga
        self.obszar = obszar
        self.naglowki = naglowki


def profil(klucz, token):
    """
    Rozkład ruchu bez scenariuszy płatnych.

    Udziały jak w planie testu, po odjęciu rozmowy i kontaktu: odwiedzający
    głównie czytają, panel to pojedyncze osoby.
    """
    widget = {"X-API-Key": klucz} if klucz else None
    panel = {"Authorization": f"Bearer {token}"} if token else None

    scenariusze = []
    if widget:
        scenariusze += [
            Scenariusz("widget: ustawienia", "/api/widget-settings/", 45, "widget", widget),
            Scenariusz("widget: FAQ", "/api/widget/faq/", 25, "widget", widget),
        ]
    if panel:
        scenariusze += [
            Scenariusz("panel: pulpit", "/api/analytics/", 10, "panel", panel),
            Scenariusz("panel: historia", "/api/chat/logs/?page=1", 10, "panel", panel),
            Scenariusz("panel: dokumenty", "/api/documents/?page=1", 10, "panel", panel),
        ]
    return scenariusze


def wyslij(adres, scenariusz, limit_czasu=30):
    """Zwraca (kod odpowiedzi, czas w ms). Kod 0 oznacza brak odpowiedzi."""
    zadanie = urllib.request.Request(adres + scenariusz.sciezka, headers=scenariusz.naglowki or {})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(zadanie, timeout=limit_czasu) as odpowiedz:
            odpowiedz.read()
            kod = odpowiedz.status
    except urllib.error.HTTPError as blad:
        blad.read()
        kod = blad.code
    except Exception:
        kod = 0
    return kod, (time.perf_counter() - start) * 1000


def podsumuj(wyniki):
    """Statystyki na scenariusz: liczba, p50, p95, maksimum i rozkład kodów."""
    podsumowanie = {}
    for nazwa, pomiary in wyniki.items():
        czasy = sorted(czas for _, czas in pomiary)
        kody = defaultdict(int)
        for kod, _ in pomiary:
            kody[kod] += 1
        podsumowanie[nazwa] = {
            "ile": len(czasy),
            "p50": statistics.median(czasy) if czasy else 0,
            # Indeks, nie interpolacja: przy kilkuset pomiarach różnica jest
            # poniżej milisekundy, a wynik da się sprawdzić ołówkiem.
            "p95": czasy[min(len(czasy) - 1, int(len(czasy) * 0.95))] if czasy else 0,
            "max": max(czasy) if czasy else 0,
            "kody": dict(sorted(kody.items())),
        }
    return podsumowanie


def ocena(podsumowanie, obszary):
    """Lista zdań o niedotrzymanych progach. Pusta lista znaczy: mieści się w SLO."""
    uwagi = []
    wszystkie = sum(dane["ile"] for dane in podsumowanie.values())
    bledy = sum(
        ile for dane in podsumowanie.values() for kod, ile in dane["kody"].items() if kod >= 500
    )
    for nazwa, dane in podsumowanie.items():
        prog = PROGI_P95[obszary[nazwa]]
        if dane["p95"] > prog:
            uwagi.append(f"{nazwa}: p95 {dane['p95']:.0f} ms powyżej progu {prog} ms")
    if wszystkie and bledy / wszystkie > PROG_BLEDOW:
        uwagi.append(f"odpowiedzi 5xx: {bledy}/{wszystkie} powyżej {PROG_BLEDOW:.1%}")
    return uwagi


class Command(BaseCommand):
    help = "Mierzy czasy odpowiedzi API pod zadanym obciążeniem (bez scenariuszy płatnych)."

    def add_arguments(self, parser):
        parser.add_argument("--adres", default="http://localhost:8000", help="Adres API.")
        parser.add_argument("--klucz", default="", help="Klucz widgetu (X-API-Key).")
        parser.add_argument("--token", default="", help="Token dostępu panelu (JWT).")
        parser.add_argument("--rps", type=float, default=4.0, help="Żądań na sekundę.")
        parser.add_argument("--czas", type=int, default=30, help="Czas pomiaru w sekundach.")

    def handle(self, *args, **opcje):
        scenariusze = profil(opcje["klucz"], opcje["token"])
        if not scenariusze:
            raise CommandError(
                "Podaj --klucz (widget) albo --token (panel), inaczej nie ma co mierzyć."
            )

        adres = opcje["adres"].rstrip("/")
        if "localhost" not in adres and "127.0.0.1" not in adres:
            self.stdout.write(
                self.style.WARNING(
                    f"Mierzysz {adres}, a nie maszynę lokalną. Ruch obciąży tamten system "
                    "i zużyje limity planu firmy, do której należy klucz."
                )
            )

        # Kolejka żądań rozpisana z góry: przy stałym tempie łatwiej odtworzyć
        # przebieg niż przy losowaniu w trakcie.
        plan = []
        łącznie = int(opcje["rps"] * opcje["czas"])
        suma_wag = sum(s.waga for s in scenariusze)
        for scenariusz in scenariusze:
            plan += [scenariusz] * max(1, round(łącznie * scenariusz.waga / suma_wag))

        wyniki = defaultdict(list)
        blokada = threading.Lock()
        odstep = 1 / opcje["rps"]
        watki = []
        start = time.perf_counter()

        for numer, scenariusz in enumerate(plan):
            docelowy = start + numer * odstep
            opoznienie = docelowy - time.perf_counter()
            if opoznienie > 0:
                time.sleep(opoznienie)

            def zadanie(scenariusz=scenariusz):
                kod, czas = wyslij(adres, scenariusz)
                with blokada:
                    wyniki[scenariusz.nazwa].append((kod, czas))

            watek = threading.Thread(target=zadanie, daemon=True)
            watek.start()
            watki.append(watek)

        for watek in watki:
            watek.join()

        trwanie = time.perf_counter() - start
        podsumowanie = podsumuj(wyniki)
        obszary = {s.nazwa: s.obszar for s in scenariusze}

        tempo = len(plan) / trwanie
        self.stdout.write(f"\nPomiar: {len(plan)} żądań w {trwanie:.1f} s ({tempo:.1f}/s)\n")
        self.stdout.write(f"{'scenariusz':24} {'ile':>5} {'p50':>8} {'p95':>8} {'max':>8}  kody")
        for nazwa, dane in podsumowanie.items():
            kody = " ".join(f"{kod}:{ile}" for kod, ile in dane["kody"].items())
            self.stdout.write(
                f"{nazwa:24} {dane['ile']:>5} {dane['p50']:>7.0f}ms {dane['p95']:>7.0f}ms "
                f"{dane['max']:>7.0f}ms  {kody}"
            )

        uwagi = ocena(podsumowanie, obszary)
        if uwagi:
            self.stdout.write(self.style.ERROR("\nPoza SLO:"))
            for uwaga in uwagi:
                self.stdout.write(self.style.ERROR(f"  - {uwaga}"))
        else:
            self.stdout.write(self.style.SUCCESS("\nWszystkie progi SLO dotrzymane."))
