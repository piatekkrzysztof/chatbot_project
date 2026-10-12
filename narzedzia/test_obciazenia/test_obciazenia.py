"""
Mały test obciążenia produkcji - decyzja właściciela z 11.10.2026.

Mierzy progi z docs/slo-i-czasy-odpowiedzi.md przy ruchu, jaki generuje
jedna firma na planie próbnym, na koncie testowym, poza godzinami pracy:

  • widget: ustawienia i FAQ (odczyty, bez kosztu modelu),
  • panel: pulpit, historia rozmów, dokumenty, co jakiś czas eksport CSV,
  • rozmowy z botem strumieniem - czas do pierwszych słów i całej odpowiedzi.

Limity planu są częścią systemu, nie przeszkodą: domyślne tempo mieści się
pod nimi (widget 60/min na firmę, czat 20 wiadomości na godzinę z jednego
adresu), więc każda odpowiedź 429 to wynik do wyjaśnienia, nie szum.

Koszt modelu: ok. 0,0005 zł na wiadomość w pomiarze z docs/wybor-modelu.md,
najwyżej kilka tysięcznych złotego przy pełnym kontekście - 20 rozmów to
grosze, daleko pod limitem 20 zł z decyzji. Rozmowy trafiają do historii
i statystyk konta testowego.

    python narzedzia/test_obciazenia/test_obciazenia.py \\
        --backend https://api.agencjasm-art.pl \\
        --panel https://panel.agencjasm-art.pl \\
        --klucz KLUCZ_WIDGETU_KONTA_TESTOWEGO \\
        --strona https://cdpn.io

Pyta o e-mail i hasło konta testowego (hasło niewidoczne, nigdzie nie
zapisywane). Wynik: tabela w terminalu i plik JSON obok skryptu. Kod wyjścia 1,
gdy któryś próg SLO nie jest dotrzymany. Ctrl+C przerywa i pokazuje wyniki
zebrane do tej pory.
"""

import argparse
import getpass
import json
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

TU = Path(__file__).parent

#: Progi wprost z SLO. (rodzaj, percentyl 95 w ms, najdłuższe dopuszczalne w ms)
PROGI = {
    "widget": (500, None),
    "panel": (800, 3000),
    "czat_pierwsze_slowa": (3000, None),
}
PROG_5XX = 0.005

PYTANIA = [
    "Jakie macie godziny otwarcia?",
    "Ile kosztuje Wasza najtańsza usługa?",
    "Czy można u Was zapłacić kartą?",
    "Jak mogę się z Wami skontaktować?",
    "Czy pracujecie w weekendy?",
    "Gdzie się znajdujecie?",
    "Czy macie jakieś promocje?",
    "Jak długo trwa realizacja zamówienia?",
]

MAKS_ROZMOW = 20  # limit odwiedzającego: 20 wiadomości na godzinę z jednego adresu
MAKS_ODCZYTOW_NA_S = 0.9  # widget planu próbnego: 60/min na firmę


class Wyniki:
    def __init__(self):
        self.blokada = threading.Lock()
        self.pomiary = []  # (rodzaj, trasa, status, ms, dodatkowe)

    def dodaj(self, rodzaj, trasa, status, ms, **dodatkowe):
        with self.blokada:
            self.pomiary.append((rodzaj, trasa, status, ms, dodatkowe))


def p95(wartosci):
    if not wartosci:
        return None
    if len(wartosci) == 1:
        return wartosci[0]
    return statistics.quantiles(wartosci, n=20, method="inclusive")[18]


def zaloguj(api, panel):
    email = input("E-mail konta testowego: ").strip()
    haslo = getpass.getpass("Hasło (niewidoczne): ")
    naglowki = {"Origin": panel}
    with httpx.Client(timeout=30) as k:
        r = k.post(
            f"{api}/accounts/login/", json={"username": email, "password": haslo}, headers=naglowki
        )
        del haslo
        dane = r.json() if r.content else {}
        if r.status_code == 200 and dane.get("wymaga_drugiego_skladnika"):
            kod = input("Kod z aplikacji uwierzytelniającej: ").strip()
            r = k.post(
                f"{api}/accounts/login/2fa/",
                json={"bilet": dane["bilet"], "kod": kod},
                headers=naglowki,
            )
            dane = r.json() if r.content else {}
    if r.status_code != 200 or "access" not in dane:
        sys.exit(
            f"Logowanie nieudane ({r.status_code}): "
            f"{dane.get('error') or dane.get('detail') or dane}"
        )
    return dane["access"]


def get(klient, wyniki, rodzaj, url, naglowki, trasa):
    start = time.perf_counter()
    try:
        r = klient.get(url, headers=naglowki)
        r.read()
        status = r.status_code
    except httpx.HTTPError as blad:
        status = f"blad:{type(blad).__name__}"
    wyniki.dodaj(rodzaj, trasa, status, (time.perf_counter() - start) * 1000)


def rozmowa(klient, wyniki, api, klucz, strona, pytanie):
    # Bez Accept: text/event-stream - widget go nie wysyła, a DRF odpowiada
    # na niego 406 (negocjacja treści zna tylko JSON).
    naglowki = {"X-API-KEY": klucz, "Origin": strona}
    cialo = {"message": pytanie, "conversation_session_id": str(uuid.uuid4())}
    start = time.perf_counter()
    pierwsze = None
    status = None
    tokeny = None
    try:
        with klient.stream(
            "POST", f"{api}/widget/chat/stream/", json=cialo, headers=naglowki, timeout=60
        ) as r:
            status = r.status_code
            for linia in r.iter_lines():
                if not linia.startswith("data:"):
                    continue
                zdarzenie = json.loads(linia[5:].strip() or "{}")
                if (
                    zdarzenie.get("type") == "delta"
                    and zdarzenie.get("content")
                    and pierwsze is None
                ):
                    pierwsze = (time.perf_counter() - start) * 1000
                if zdarzenie.get("type") == "done":
                    tokeny = zdarzenie.get("tokens")
    except httpx.HTTPError as blad:
        status = f"blad:{type(blad).__name__}"
    calosc = (time.perf_counter() - start) * 1000
    wyniki.dodaj(
        "czat_pierwsze_slowa",
        "widget/chat/stream",
        status,
        pierwsze,
        calosc_ms=calosc,
        tokeny=tokeny,
    )


def w_tempie(stop, na_sekunde, zadanie, pula):
    """Zleca zadanie w stałym tempie do chwili zatrzymania."""
    if na_sekunde <= 0:
        return
    odstep = 1 / na_sekunde
    nastepne = time.perf_counter()
    while not stop.is_set():
        pula.submit(zadanie)
        nastepne += odstep
        stop.wait(max(0.0, nastepne - time.perf_counter()))


def raport(wyniki, sekund, plik):
    print()
    print(f"{'rodzaj':22} {'żądań':>6} {'p50 ms':>8} {'p95 ms':>8} {'maks ms':>8}  statusy")
    zaliczone = True
    podsumowanie = {}
    wszystkie = len(wyniki.pomiary)
    bledy_5xx = sum(1 for p in wyniki.pomiary if isinstance(p[2], int) and p[2] >= 500)
    nie_http = sum(1 for p in wyniki.pomiary if not isinstance(p[2], int))
    for rodzaj in ("widget", "panel", "czat_pierwsze_slowa", "eksport"):
        wiersze = [p for p in wyniki.pomiary if p[0] == rodzaj]
        if not wiersze:
            continue
        czasy = sorted(p[3] for p in wiersze if p[3] is not None and p[2] == 200)
        statusy = {}
        for p in wiersze:
            statusy[str(p[2])] = statusy.get(str(p[2]), 0) + 1
        mediana = statistics.median(czasy) if czasy else None
        p95_ms = p95(czasy)
        maks = max(czasy) if czasy else None
        werdykt = ""
        if rodzaj in PROGI:
            prog95, prog_maks = PROGI[rodzaj]
            ok = p95_ms is not None and p95_ms < prog95 and (prog_maks is None or maks < prog_maks)
            werdykt = "OK" if ok else "PRZEKROCZONE"
            zaliczone &= ok

        def f(x):
            return f"{x:8.0f}" if x is not None else "       -"

        uwaga = " (mało próbek - p95 to prawie maksimum)" if 0 < len(czasy) < 10 else ""
        print(
            f"{rodzaj:22} {len(wiersze):6} {f(mediana)} {f(p95_ms)} {f(maks)}  "
            f"{statusy} {werdykt}{uwaga}"
        )
        podsumowanie[rodzaj] = {
            "zadan": len(wiersze),
            "p50_ms": mediana,
            "p95_ms": p95_ms,
            "maks_ms": maks,
            "statusy": statusy,
            "werdykt": werdykt or None,
        }
        if rodzaj == "czat_pierwsze_slowa":
            calosci = sorted(p[4]["calosc_ms"] for p in wiersze if p[2] == 200)
            if calosci:
                print(
                    f"{'  cała odpowiedź':22} {'':6} {statistics.median(calosci):8.0f} "
                    f"{p95(calosci):8.0f} {max(calosci):8.0f}"
                )
                podsumowanie[rodzaj]["calosc_p50_ms"] = statistics.median(calosci)
                podsumowanie[rodzaj]["calosc_p95_ms"] = p95(calosci)
    udzial_5xx = (bledy_5xx + nie_http) / wszystkie if wszystkie else 0
    ok_5xx = udzial_5xx < PROG_5XX
    zaliczone &= ok_5xx
    odmowy_429 = sum(1 for p in wyniki.pomiary if p[2] == 429)
    print()
    print(
        f"Błędy 5xx i sieci: {bledy_5xx + nie_http} z {wszystkie} ({udzial_5xx:.2%}) - "
        f"{'OK' if ok_5xx else 'PRZEKROCZONE'} (próg 0,5%)"
    )
    print(
        f"Odmowy 429: {odmowy_429}"
        + (" - do wyjaśnienia: tempo testu mieści się w limitach planu" if odmowy_429 else "")
    )
    print(f"Czas testu: {sekund:.0f} s")
    print(
        "\nWYNIK: "
        + (
            "progi SLO dotrzymane"
            if zaliczone and not odmowy_429
            else "NIE WSZYSTKO W PROGACH - wklej ten wynik"
        )
    )
    plik.write_text(
        json.dumps(
            {
                "czas": datetime.now(UTC).isoformat(),
                "sekund": round(sekund),
                "podsumowanie": podsumowanie,
                "bledy_5xx_udzial": udzial_5xx,
                "odmowy_429": odmowy_429,
            },
            indent=1,
            ensure_ascii=False,
        )
    )
    print(f"Zapisano: {plik}")
    return zaliczone and not odmowy_429


def main():
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--backend", required=True)
    a.add_argument(
        "--panel", required=True, help="Adres panelu (nagłówek Origin dla panelu i logowania)"
    )
    a.add_argument(
        "--klucz", required=True, help="Klucz API widgetu konta testowego (jest w kodzie osadzenia)"
    )
    a.add_argument(
        "--strona",
        required=True,
        help="Witryna zarejestrowana dla widgetu konta testowego (Origin)",
    )
    a.add_argument("--czas", type=int, default=600, help="Sekundy ruchu odczytów (domyślnie 600)")
    a.add_argument("--odczyty-na-s", type=float, default=0.8)
    a.add_argument("--panel-na-s", type=float, default=2.0)
    a.add_argument("--rozmowy", type=int, default=15)
    o = a.parse_args()

    if o.rozmowy > MAKS_ROZMOW:
        sys.exit(
            f"Najwyżej {MAKS_ROZMOW} rozmów - limit odwiedzającego to 20 wiadomości na godzinę."
        )
    if o.odczyty_na_s > MAKS_ODCZYTOW_NA_S:
        sys.exit(
            f"Najwyżej {MAKS_ODCZYTOW_NA_S}/s odczytów widgetu - limit planu próbnego to 60/min."
        )

    api = o.backend.rstrip("/") + "/api"
    panel = o.panel.rstrip("/")
    token = zaloguj(api, panel)
    wyniki = Wyniki()
    stop = threading.Event()
    widget_naglowki = {"X-API-KEY": o.klucz, "Origin": o.strona}
    panel_naglowki = {"Authorization": f"Bearer {token}", "Origin": panel}
    trasy_panelu = ["/analytics/", "/chat/logs/?page=1", "/documents/?page=1"]
    licznik_panelu = [0]

    print(
        f"\nStart {datetime.now():%H:%M:%S}: {o.czas} s, widget {o.odczyty_na_s}/s, "
        f"panel {o.panel_na_s}/s, {o.rozmowy} rozmów. Ctrl+C przerywa."
    )
    start = time.perf_counter()
    with (
        httpx.Client(timeout=30, limits=httpx.Limits(max_connections=40)) as klient,
        ThreadPoolExecutor(max_workers=40) as pula,
    ):

        def widget():
            sciezka = "/widget-settings/" if uuid.uuid4().int % 2 else "/widget/faq/"
            get(klient, wyniki, "widget", api + sciezka, widget_naglowki, sciezka)

        def panel_zadanie():
            licznik_panelu[0] += 1
            if licznik_panelu[0] % 60 == 0:
                get(
                    klient,
                    wyniki,
                    "eksport",
                    api + "/chat/export/",
                    panel_naglowki,
                    "/chat/export/",
                )
                return
            sciezka = trasy_panelu[licznik_panelu[0] % len(trasy_panelu)]
            get(klient, wyniki, "panel", api + sciezka, panel_naglowki, sciezka)

        def rozmowy():
            odstep = o.czas / max(o.rozmowy, 1)
            for i in range(o.rozmowy):
                if stop.wait(odstep / 2 if i == 0 else odstep):
                    return
                pula.submit(
                    rozmowa, klient, wyniki, api, o.klucz, o.strona, PYTANIA[i % len(PYTANIA)]
                )

        watki = [
            threading.Thread(
                target=w_tempie, args=(stop, o.odczyty_na_s, widget, pula), daemon=True
            ),
            threading.Thread(
                target=w_tempie, args=(stop, o.panel_na_s, panel_zadanie, pula), daemon=True
            ),
            threading.Thread(target=rozmowy, daemon=True),
        ]
        for w in watki:
            w.start()
        try:
            while time.perf_counter() - start < o.czas:
                time.sleep(15)
                ile = len(wyniki.pomiary)
                print(f"  {time.perf_counter() - start:4.0f} s: {ile} żądań")
        except KeyboardInterrupt:
            print("\nPrzerwano - kończę rozpoczęte żądania.")
        stop.set()
        for w in watki:
            w.join(timeout=5)
        pula.shutdown(wait=True)
        try:
            klient.post(f"{api}/accounts/logout/", json={}, headers=panel_naglowki)
        except httpx.HTTPError:
            pass
    sekund = time.perf_counter() - start
    plik = TU / f"wynik-{datetime.now():%Y%m%d-%H%M}.json"
    sys.exit(0 if raport(wyniki, sekund, plik) else 1)


if __name__ == "__main__":
    main()
