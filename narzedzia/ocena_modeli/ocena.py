"""
Porównanie modeli czatu na wiedzy z czterech dokumentów testowych.

Każdy model dostaje identyczny kontekst: fragmenty z prawdziwego podziału
i wyszukiwania oraz prompt systemowy z produkcji. Odpowiedzi idą strumieniem,
jak w widgecie. Mierzy trafność (fakty, wnioskowanie), odmowy ze znacznikiem,
czas do pierwszych słów i realne zużycie tokenów - z rozumowaniem włącznie.

    python narzedzia/ocena_modeli/ocena.py gpt-4o-mini "gpt-6-luna|medium"
    python narzedzia/ocena_modeli/ocena.py "gpt-6-luna|low" --powtorzenia 3

Model z „|wartość" dostaje taki reasoning_effort. Temperatura 0,2 jest
wysyłana tylko modelom, które ją przyjmują - inne dostają domyślną.

Koszt: wywołania OpenAI na kluczu z .env, kilka centów na model. Baza:
lokalna, dane w transakcji wycofywanej na końcu. Wyniki: docs/wybor-modelu.md.
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TU = Path(__file__).resolve().parent
sys.path.insert(0, str(TU.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot_project.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402
from openai import BadRequestError, OpenAI  # noqa: E402

import rag.engine as silnik  # noqa: E402
from accounts.models import Tenant  # noqa: E402
from api.utils.pokrycie import ZNACZNIK_BRAKU  # noqa: E402
from api.utils.prompt_systemowy import build_system_prompt  # noqa: E402
from documents.file_limits import extract_docx, read_text  # noqa: E402
from documents.models import Document, DocumentChunk  # noqa: E402
from documents.utils import fragmenty as podzial  # noqa: E402
from documents.utils.pdf_parser import extract_text_from_pdf  # noqa: E402
from documents.wymiar import WYMIAR_WEKTORA  # noqa: E402

DOK = TU / "dokumenty"

#: Ceny za 1 mln tokenów (USD, wejście, wyjście), cennik OpenAI 8.10.2026:
#: developers.openai.com/api/docs/pricing. Model spoza listy - koszt „?".
CENY = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
}
KURS_USD = 4.0

#: (pytanie, grupa, warianty poprawnej odpowiedzi). Pytanie o dowóz na 40 km
#: z pomiaru 8.10 jest usunięte: dwa dokumenty podają tam sprzeczne stawki
#: i lepsze modele słusznie odmawiały - mierzyło to dane, nie model.
PYTANIA = [
    ("Ile kosztuje figurka z masy cukrowej?", "fakt", ["45 zł", "45 zl"]),
    ("Macie złocenia? Ile to kosztuje?", "fakt", ["60 zł", "60 zl"]),
    ("Jakie kwiaty jadalne macie?", "fakt", ["bratk", "róż", "chabr"]),
    ("Jak długo można przechowywać tort z owocami?", "fakt", ["48"]),
    ("Do kiedy mogę anulować zamówienie tortu bez utraty zaliczki?", "fakt", ["7 dni"]),
    ("Jaka jest minimalna kwota zamówienia z dowozem?", "fakt", ["150"]),
    ("W jakie dni mogę odebrać tort osobiście?", "fakt", ["wtor"]),
    ("Do kiedy mogę zmienić smak tortu?", "fakt", ["5 dni"]),
    ("Czy wysyłacie torty kurierem?", "fakt", ["nie wysyła", "chłodni", "sami dowozimy"]),
    ("Ile mam czasu na reklamację?", "fakt", ["24"]),
    ("Ile kosztuje Bufet Premium za osobę?", "fakt", ["139"]),
    ("Ile kosztuje pakiet dla dzieci?", "fakt", ["49"]),
    ("Ile trzeba dopłacić za wersję wegańską?", "fakt", ["12 zł", "12 zl"]),
    ("W jakich godzinach działa biuro cateringu?", "fakt", ["8-16", "8–16", "8:00", "8 do 16"]),
    ("Czy wystawiacie faktury?", "fakt", ["VAT", "faktur"]),
    ("Ile kosztuje degustacja cateringu?", "fakt", ["60 zł", "60 zl"]),
    ("Co jeśli odwołam przyjęcie 10 dni wcześniej?", "wnioskowanie", ["połow", "50%"]),
    ("Ile zapłacę za kelnera na 5 godzin?", "wnioskowanie", ["225"]),
    ("Ile będzie kosztował Bufet Premium dla 25 osób?", "wnioskowanie", ["3475", "3 475"]),
    ("Czy dostanę rabat, jeśli będzie 90 gości?", "wnioskowanie", ["8%", "8 %", "8 proc"]),
    ("Zamawiam 3 dekoracje: figurkę, napis i topper. Ile zapłacę?", "wnioskowanie", ["75"]),
    ("Czy mogę zamówić Obiad serwowany dla 20 osób?", "wnioskowanie", ["30", "minimum"]),
    ("Jaka jest stolica Australii?", "odmowa", []),
    ("Czy robicie torty w kształcie samochodu wyścigowego?", "odmowa", []),
    ("Czy sprzedajecie kawę na wynos?", "odmowa", []),
    ("Czy macie parking dla klientów?", "odmowa", []),
    ("Czy organizujecie wesela z zespołem muzycznym?", "odmowa", []),
    ("Czy macie fontannę czekoladową?", "odmowa", []),
    ("Czy wynajmujecie salę na 100 osób?", "odmowa", []),
    ("Ile wynosi pierwiastek z 256?", "odmowa", []),
    ("Dzień dobry", "uprzejmość", []),
    ("Dziękuję, do widzenia", "uprzejmość", []),
]


def wczytaj_dokumenty():
    return {
        "cennik-dekoracji-test1.docx": extract_docx(
            (DOK / "cennik-dekoracji-test1.docx").read_bytes()
        ),
        "przechowywanie-tortow-ansi.txt": read_text(
            (DOK / "przechowywanie-tortow-ansi.txt").read_bytes()
        ),
        "regulamin-zamowien-test1.pdf": extract_text_from_pdf(
            (DOK / "regulamin-zamowien-test1.pdf").open("rb")
        ),
        "oferta-cateringu-test.pdf": extract_text_from_pdf(
            (DOK / "oferta-cateringu-test.pdf").open("rb")
        ),
    }


def zbuduj_konteksty(klient):
    """Prompt systemowy dla każdego pytania - jeden dla wszystkich modeli."""

    def wektory(teksty):
        wynik = []
        for i in range(0, len(teksty), 64):
            odp = klient.embeddings.create(
                input=teksty[i : i + 64],
                model=settings.OPENAI_EMBEDDING_MODEL,
                dimensions=WYMIAR_WEKTORA,
            )
            wynik += [d.embedding for d in odp.data]
        return wynik

    silnik.client = klient
    konteksty = {}
    with transaction.atomic():
        firma = Tenant.objects.create(name="Ocena modeli", owner_email="ocena@example.invalid")
        for nazwa, tresc in wczytaj_dokumenty().items():
            # processed=False: inaczej sygnał zleciłby własne embeddingi.
            dok = Document.objects.create(tenant=firma, name=nazwa, content=tresc, processed=False)
            czesci = podzial.podziel_na_fragmenty(tresc)
            teksty = [podzial.tekst_do_wektora(c, nazwa) for c in czesci]
            for czesc, wektor in zip(czesci, wektory(teksty), strict=True):
                DocumentChunk.objects.create(document=dok, content=czesc, embedding=wektor)
        for pytanie, _, _ in PYTANIA:
            fragmenty = silnik.query_similar_chunks_pgvector(firma.id, pytanie)
            for f in fragmenty:
                _ = f.document  # dociągnięte, zanim transakcja zniknie
            konteksty[pytanie] = build_system_prompt(firma, fragmenty, [], pytanie)
        transaction.set_rollback(True)
    return konteksty


def zapytaj(klient, konteksty, model, pytanie):
    nazwa, _, wysilek = model.partition("|")
    wiadomosci = [
        {"role": "system", "content": konteksty[pytanie]},
        {"role": "user", "content": pytanie},
    ]
    parametry = {
        "max_completion_tokens": settings.OPENAI_MAX_OUTPUT_TOKENS,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if wysilek:
        parametry["reasoning_effort"] = wysilek
    start = time.perf_counter()
    try:
        strumien = klient.chat.completions.create(model=nazwa, messages=wiadomosci, **parametry)
    except BadRequestError:
        parametry.pop("temperature")  # model przyjmuje tylko domyślną
        start = time.perf_counter()
        strumien = klient.chat.completions.create(model=nazwa, messages=wiadomosci, **parametry)
    czesci, pierwsze, wejscie, wyjscie = [], None, 0, 0
    for zdarzenie in strumien:
        if zdarzenie.usage:
            wejscie, wyjscie = zdarzenie.usage.prompt_tokens, zdarzenie.usage.completion_tokens
        if zdarzenie.choices and zdarzenie.choices[0].delta.content:
            if pierwsze is None:
                pierwsze = time.perf_counter() - start
            czesci.append(zdarzenie.choices[0].delta.content)
    return "".join(czesci).strip(), pierwsze or time.perf_counter() - start, wejscie, wyjscie


def ocen(klient, konteksty, model, powtorzenia):
    zestaw = PYTANIA * powtorzenia
    with ThreadPoolExecutor(max_workers=6) as pula:
        odpowiedzi = list(pula.map(lambda p: zapytaj(klient, konteksty, model, p[0]), zestaw))
    grupy: dict[str, list[int]] = {}
    bledy, czasy, puste, tok_we, tok_wy = [], [], 0, 0, 0
    for (pytanie, grupa, warianty), (tekst, czas, we, wy) in zip(zestaw, odpowiedzi, strict=True):
        tok_we, tok_wy = tok_we + we, tok_wy + wy
        czasy.append(czas)
        puste += not tekst
        odmowa = tekst.startswith(ZNACZNIK_BRAKU)
        if grupa in ("fakt", "wnioskowanie"):
            dobrze = not odmowa and any(w.lower() in tekst.lower() for w in warianty)
        elif grupa == "odmowa":
            dobrze = odmowa
        else:
            dobrze = bool(tekst) and not odmowa
        grupy.setdefault(grupa, [0, 0])
        grupy[grupa][0] += dobrze
        grupy[grupa][1] += 1
        if not dobrze:
            bledy.append(f"[{grupa}] {pytanie} -> {tekst[:110]!r}")
    n = len(zestaw)
    ceny = CENY.get(model.partition("|")[0])
    koszt = (
        f"{(tok_we * ceny[0] + tok_wy * ceny[1]) / 1e6 / n * KURS_USD:.4f} zł" if ceny else "? zł"
    )
    czasy.sort()
    print(
        f"{model:20} "
        + "  ".join(f"{g} {d}/{w}" for g, (d, w) in grupy.items())
        + f"  puste {puste}  koszt {koszt}  wyjście {tok_wy / n:.0f} tok"
        + f"  1. słowa mediana/p95 {czasy[n // 2]:.1f}/{czasy[int(n * 0.95)]:.1f} s"
    )
    for blad in bledy:
        print("    ", blad)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("modele", nargs="+")
    parser.add_argument("--powtorzenia", type=int, default=2)
    opcje = parser.parse_args()
    klient = OpenAI(api_key=settings.OPENAI_API_KEY)
    konteksty = zbuduj_konteksty(klient)
    for model in opcje.modele:
        ocen(klient, konteksty, model, opcje.powtorzenia)


if __name__ == "__main__":
    main()
