"""Jeden scenariusz pomiaru: N równoczesnych rozmów (+ opcjonalnie upload) i panel w tle.

Użycie: python obciazenie.py ROZMOWY FIRMY UPLOAD(0/1) ETYKIETA
Wynik dopisywany do wyniki.jsonl obok skryptu.
"""

import io
import json
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
from reportlab.pdfgen import canvas

TU = Path(__file__).parent
URL = "http://localhost:18000/api"
KONTENER = "pomiar-20261007-web"

rozmowy, firmy, upload, etykieta = (
    int(sys.argv[1]),
    int(sys.argv[2]),
    sys.argv[3] == "1",
    sys.argv[4],
)
dane = json.loads((TU / "dane.json").read_text())


def pamiec():
    # cgroup v1 (Docker Desktop/WSL). Produkcja ma v2; liczymy przyrosty.
    wynik = subprocess.run(
        [
            "docker",
            "exec",
            KONTENER,
            "sh",
            "-c",
            "cd /sys/fs/cgroup/memory; cat memory.usage_in_bytes;"
            " grep -E '^(total_rss|total_cache) ' memory.stat; cat memory.failcnt;"
            " grep oom_kill memory.oom_control | grep -v disable",
        ],
        capture_output=True,
        text=True,
    ).stdout.split()
    return {
        "current": int(wynik[0]),
        "anon": int(wynik[4]),
        "file": int(wynik[2]),
        "max_events": int(wynik[5]),
        "oom_kill": int(wynik[7]),
    }


probki: list[int] = []
koniec = threading.Event()


def probkuj():
    proces = subprocess.Popen(
        [
            "docker",
            "exec",
            KONTENER,
            "sh",
            "-c",
            "while true; do cat /sys/fs/cgroup/memory/memory.usage_in_bytes; sleep 0.1; done",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    for linia in proces.stdout:
        probki.append(int(linia))
        if koniec.is_set():
            break
    proces.kill()


panel: list[tuple[int, float]] = []


RAZEM = int(__import__("os").environ.get("PANEL_ROWNOLEGLE", "1"))


def panel_jedno():
    with httpx.Client(timeout=30) as klient:
        start = time.monotonic()
        odp = klient.get(
            f"{URL}/accounts/me/", headers={"Authorization": f"Bearer {dane[0]['token']}"}
        )
        panel.append((odp.status_code, time.monotonic() - start))


def panel_w_tle():
    # Pulpit ładuje kilka list naraz; RAZEM żądań równolegle co pół sekundy.
    while not koniec.is_set():
        paczka = [threading.Thread(target=panel_jedno) for _ in range(RAZEM)]
        for w in paczka:
            w.start()
        for w in paczka:
            w.join()
        time.sleep(0.5)


wyniki_rozmow: list[dict] = []
start_bariera = threading.Barrier(rozmowy + (1 if upload else 0))


def rozmowa(numer):
    firma = dane[numer % firmy]
    start_bariera.wait()
    start = time.monotonic()
    pierwszy = None
    zakonczona = False
    with httpx.Client(timeout=120) as klient:
        with klient.stream(
            "POST",
            f"{URL}/widget/chat/stream/",
            headers={"X-API-Key": firma["api_key"]},
            json={
                "message": "Jakie macie torty na chrzciny i ile kosztują?",
                "conversation_session_id": str(uuid.uuid4()),
            },
        ) as odp:
            status = odp.status_code
            for kawalek in odp.iter_text():
                if pierwszy is None and kawalek:
                    pierwszy = time.monotonic() - start
                if '"done"' in kawalek:
                    zakonczona = True
    wyniki_rozmow.append(
        {
            "status": status,
            "pierwszy": pierwszy,
            "czas": time.monotonic() - start,
            "done": zakonczona,
            "firma": numer % firmy,
        }
    )


wynik_uploadu: dict = {}


def pdf_200_stron():
    bufor = io.BytesIO()
    plotno = canvas.Canvas(bufor)
    for strona in range(200):
        for wiersz in range(40):
            plotno.drawString(
                40,
                800 - wiersz * 19,
                f"Strona {strona} wiersz {wiersz}: tort weselny, dekoracje, cennik usług cukierni.",
            )
        plotno.showPage()
    plotno.save()
    return bufor.getvalue()


def wgraj(plik):
    start_bariera.wait()
    time.sleep(1.0)  # rozmowy są już w toku, gdy przychodzi plik
    start = time.monotonic()
    with httpx.Client(timeout=120) as klient:
        odp = klient.post(
            f"{URL}/documents-upload/",
            headers={"Authorization": f"Bearer {dane[0]['token']}"},
            files={"file": (f"cennik-{uuid.uuid4().hex[:6]}.pdf", plik, "application/pdf")},
        )
    wynik_uploadu.update(
        {
            "status": odp.status_code,
            "czas": time.monotonic() - start,
            "bajty": len(plik),
            "odpowiedz": odp.text[:200],
        }
    )


przed = pamiec()
plik = pdf_200_stron() if upload else None
watki = [
    threading.Thread(target=probkuj, daemon=True),
    threading.Thread(target=panel_w_tle, daemon=True),
]
for w in watki:
    w.start()
time.sleep(1.0)
robocze = [threading.Thread(target=rozmowa, args=(i,)) for i in range(rozmowy)]
if upload:
    robocze.append(threading.Thread(target=wgraj, args=(plik,)))
for w in robocze:
    w.start()
for w in robocze:
    w.join()
time.sleep(1.0)
koniec.set()
po = pamiec()

przyjete = [r for r in wyniki_rozmow if r["status"] == 200]
czasy_panelu = sorted(c for s, c in panel if s == 200)
podsumowanie = {
    "etykieta": etykieta,
    "rozmowy": rozmowy,
    "firmy": firmy,
    "upload": upload,
    "przyjete": len(przyjete),
    "odmowy_503": sum(r["status"] == 503 for r in wyniki_rozmow),
    "inne": sorted({r["status"] for r in wyniki_rozmow} - {200, 503}),
    "ukonczone_done": sum(r["done"] for r in przyjete),
    "pierwszy_fragment_mediana_s": round(
        statistics.median([r["pierwszy"] for r in przyjete if r["pierwszy"]]), 2
    )
    if przyjete
    else None,
    "pierwszy_fragment_max_s": round(max([r["pierwszy"] for r in przyjete if r["pierwszy"]]), 2)
    if przyjete
    else None,
    "czas_rozmowy_max_s": round(max(r["czas"] for r in przyjete), 2) if przyjete else None,
    "panel_probek": len(panel),
    "panel_bledy": sum(s != 200 for s, _ in panel),
    "panel_mediana_ms": round(statistics.median(czasy_panelu) * 1000) if czasy_panelu else None,
    "panel_max_ms": round(czasy_panelu[-1] * 1000) if czasy_panelu else None,
    "wynik_uploadu": wynik_uploadu or None,
    "pamiec_przed_mib": round(przed["current"] / 2**20, 1),
    "anon_przed_mib": round(przed["anon"] / 2**20, 1),
    "pamiec_szczyt_mib": round(max(probki) / 2**20, 1) if probki else None,
    "pamiec_po_mib": round(po["current"] / 2**20, 1),
    "anon_po_mib": round(po["anon"] / 2**20, 1),
    "oom_kill": po["oom_kill"],
    "zdarzenia_max": po["max_events"],
}
with open(TU / "wyniki.jsonl", "a", encoding="utf-8") as plik_wynikow:
    plik_wynikow.write(json.dumps(podsumowanie, ensure_ascii=False) + "\n")
print(json.dumps(podsumowanie, ensure_ascii=False, indent=1))
