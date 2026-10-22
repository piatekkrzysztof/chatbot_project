"""
Gdzie czat traci czas przed pierwszym słowem - pomiar etapów na produkcji.

Po co
-----
Test obciążenia 12.10.2026 (2.32.1): pierwsze słowa czatu p50 2,0 s, p95 3,3 s
przy celu 3 s. Sam model (gpt-6-luna, `medium`) dawał lokalnie 1,1 / 2,6 s,
a z zewnątrz widać tylko sumę. Ta komenda rozkłada ją na kroki, tymi samymi
funkcjami, którymi idzie czat:

    wektor pytania (API OpenAI) → wyszukiwanie wektorowe → trafienia po słowach
    → FAQ → prompt → model: pierwszy token → pierwszy fragment dla widgetu

Do tego koszt nowego połączenia z OpenAI: czat tworzy klienta przy każdym
pytaniu, więc każde pytanie może płacić za nawiązanie połączenia.

    python manage.py zmierz_czat --klucz KLUCZ_WIDGETU
    python manage.py zmierz_czat --klucz KLUCZ_WIDGETU --pytanie "Ile kosztuje dostawa?"

Koszt: jedno wywołanie modelu i jeden wektor na pytanie (domyślnie 8 pytań,
grosze). Niczego nie zapisuje: bez rozmowy, wiadomości, logów promptu i bez
naliczania wiadomości z planu firmy.
"""

import statistics
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Tenant
from api.utils.chat_engine import _faq_do_promptu, get_client, parametry_modelu
from api.utils.pokrycie import ObcinaczZnacznika
from api.utils.prompt_systemowy import build_system_prompt, przytnij_prompt_systemowy
from api.utils.tokens import przytnij_do_budzetu
from rag.engine import dolacz_trafienia_slowne, szukaj_po_wektorze, wektor_pytania

#: Te same pytania co w narzędziu testu obciążenia - wyniki da się zestawić.
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

#: Kolumny w kolejności drogi pytania.
KROKI = [
    ("wektor", "Wektor pytania (API OpenAI)"),
    ("szukanie", "Wyszukiwanie wektorowe (baza)"),
    ("slowa", "Trafienia po słowach (baza)"),
    ("faq", "FAQ (baza)"),
    ("prompt", "Złożenie promptu"),
    ("model", "Model: od wysłania do pierwszego tokenu"),
    ("widget", "Pierwszy fragment dla widgetu (od startu)"),
]


def ms(od):
    return (time.perf_counter() - od) * 1000


class Command(BaseCommand):
    help = "Mierzy etapy czatu przed pierwszym słowem (bez zapisu i bez naliczania)."

    def add_arguments(self, parser):
        parser.add_argument("--klucz", required=True, help="Klucz widgetu firmy (UUID).")
        parser.add_argument(
            "--pytanie",
            action="append",
            help="Własne pytanie; można podać kilka razy. Domyślnie 8 pytań testu obciążenia.",
        )

    def handle(self, *args, **opcje):
        try:
            tenant = Tenant.objects.get(api_key=opcje["klucz"])
        except (Tenant.DoesNotExist, ValidationError) as blad:
            raise CommandError("Nie ma firmy z takim kluczem widgetu.") from blad

        pytania = opcje.get("pytanie") or PYTANIA
        self.stdout.write(
            f"Model: {settings.OPENAI_CHAT_MODEL}, parametry: {parametry_modelu()}, "
            f"pytań: {len(pytania)}"
        )
        self._polaczenie(tenant)

        wyniki = []
        for pytanie in pytania:
            wynik = self._pytanie(tenant, pytanie)
            wyniki.append(wynik)
            self.stdout.write(
                f"  {wynik['widget']:6.0f} ms  wektor {wynik['wektor']:4.0f}  "
                f"model {wynik['model']:5.0f}  rozumowanie {wynik['rozumowanie']} tok.  "
                f"wejście {wynik['wejscie']} tok.  {pytanie}"
            )

        self.stdout.write("")
        self.stdout.write(f"{'Krok':45} {'mediana':>8} {'maks':>8}")
        for klucz, opis in KROKI:
            wartosci = [w[klucz] for w in wyniki]
            self.stdout.write(
                f"{opis:45} {statistics.median(wartosci):6.0f} ms {max(wartosci):6.0f} ms"
            )
        przed = [w["model_start"] for w in wyniki]
        self.stdout.write(
            f"{'Razem przed wysłaniem do modelu':45} {statistics.median(przed):6.0f} ms "
            f"{max(przed):6.0f} ms"
        )
        rozumowanie = [w["rozumowanie"] for w in wyniki if isinstance(w["rozumowanie"], int)]
        if rozumowanie:
            self.stdout.write(
                f"Tokeny rozumowania: mediana {statistics.median(rozumowanie):.0f}, "
                f"maks {max(rozumowanie)}"
            )

    def _polaczenie(self, tenant):
        """
        Nowe połączenie z OpenAI kontra już otwarte - bez tokenów.

        Odczyt opisu modelu nic nie kosztuje, a idzie tą samą drogą sieciową
        co pytanie: DNS, TCP, TLS przy nowym kliencie; samo żądanie przy starym.
        """
        model = settings.OPENAI_CHAT_MODEL
        nowe = []
        for _ in range(3):
            start = time.perf_counter()
            get_client(tenant).models.retrieve(model)
            nowe.append(ms(start))
        klient = get_client(tenant)
        klient.models.retrieve(model)
        otwarte = []
        for _ in range(3):
            start = time.perf_counter()
            klient.models.retrieve(model)
            otwarte.append(ms(start))
        self.stdout.write(
            f"Połączenie z OpenAI: nowy klient {statistics.median(nowe):.0f} ms, "
            f"otwarty {statistics.median(otwarte):.0f} ms (mediany z 3)"
        )
        self.stdout.write("")

    def _pytanie(self, tenant, pytanie):
        wynik = {}
        start = time.perf_counter()

        krok = time.perf_counter()
        wektor = wektor_pytania(pytanie)
        wynik["wektor"] = ms(krok)

        krok = time.perf_counter()
        fragmenty = szukaj_po_wektorze(tenant.id, wektor, top_k=5)
        wynik["szukanie"] = ms(krok)

        krok = time.perf_counter()
        fragmenty = dolacz_trafienia_slowne(tenant.id, pytanie, wektor, fragmenty, 5)
        wynik["slowa"] = ms(krok)

        krok = time.perf_counter()
        faq = _faq_do_promptu(tenant, pytanie)
        wynik["faq"] = ms(krok)

        krok = time.perf_counter()
        wiadomosci = [
            {"role": "system", "content": build_system_prompt(tenant, fragmenty, faq, pytanie)},
            {"role": "user", "content": pytanie},
        ]
        # Ta sama droga co w czacie - pomiar ma ciąć prompt tak, jak cięty jest naprawdę.
        wiadomosci = przytnij_do_budzetu(
            wiadomosci,
            settings.OPENAI_MAX_INPUT_TOKENS,
            przytnij_system=przytnij_prompt_systemowy,
        )
        wynik["prompt"] = ms(krok)

        wynik["model_start"] = ms(start)
        krok = time.perf_counter()
        # Jak w _stream_chat_message: nowy klient przy każdym pytaniu.
        strumien = get_client(tenant).chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=wiadomosci,
            **parametry_modelu(),
            stream=True,
            stream_options={"include_usage": True},
        )
        obcinacz = ObcinaczZnacznika()
        wynik["model"] = wynik["widget"] = None
        wynik["rozumowanie"] = wynik["wejscie"] = "?"
        try:
            for zdarzenie in strumien:
                if getattr(zdarzenie, "usage", None):
                    szczegoly = getattr(zdarzenie.usage, "completion_tokens_details", None)
                    wynik["rozumowanie"] = getattr(szczegoly, "reasoning_tokens", "?")
                    wynik["wejscie"] = getattr(zdarzenie.usage, "prompt_tokens", "?")
                if zdarzenie.choices and zdarzenie.choices[0].delta.content:
                    if wynik["model"] is None:
                        wynik["model"] = ms(krok)
                    if wynik["widget"] is None and obcinacz.podaj(
                        zdarzenie.choices[0].delta.content
                    ):
                        wynik["widget"] = ms(start)
        finally:
            zamknij = getattr(strumien, "close", None)
            if zamknij:
                zamknij()

        # Odpowiedź krótsza niż znacznik wychodzi dopiero na końcu strumienia.
        koniec = ms(start)
        wynik["model"] = koniec if wynik["model"] is None else wynik["model"]
        wynik["widget"] = koniec if wynik["widget"] is None else wynik["widget"]
        return wynik
