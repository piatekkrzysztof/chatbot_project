"""
Liczy wektory dla zestawu pomiarowego i zapisuje je do repozytorium.

Dlaczego wektory są zamrożone w pliku
-------------------------------------
Ocena wyszukiwania wymaga embeddingów, a te powstają w płatnym API, do którego
CI nie ma klucza. Można to obejść na dwa sposoby i tylko jeden jest uczciwy.

Nieuczciwy: udawany model embeddingów, który zwraca wektory zbudowane tak,
żeby pasujące teksty leżały blisko. Wtedy „trafność 100%" nie mówi nic o tym,
czy wyszukiwanie działa - mówi tylko, że atrapa jest zgodna sama ze sobą.

Uczciwy: policzyć wektory RAZ, prawdziwym modelem, i zapisać. CI liczy potem
realne odległości na realnych wektorach, deterministycznie i bez ani jednego
wywołania API. Liczby coś znaczą.

Kiedy uruchamiać
----------------
Przy zmianie modelu embeddingów albo treści zestawu pomiarowego. To jest
świadoma, rzadka czynność - wzorzec jest punktem odniesienia, więc jego
przeliczanie przy każdym niepowodzeniu testu zamieniłoby miarę w lustro.

    python manage.py zbuduj_wzorzec_rag

Kosztuje kilka setnych grosza: nieco ponad dwadzieścia krótkich tekstów.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from rag.ocena.korpus import FRAGMENTY, PYTANIA, teksty_do_zamiany_na_wektory

SCIEZKA_WZORCA = Path(__file__).resolve().parents[3] / "rag" / "ocena" / "wzorzec.json"

#: Zaokrąglenie wektorów przy zapisie.
#:
#: Sześć miejsc po przecinku zmniejsza plik o połowę, a na odległościach
#: L2 między wektorami o 1536 wymiarach zmienia wynik dopiero na dalekich
#: miejscach po przecinku - czyli poniżej progu, którym cokolwiek rozstrzygamy.
MIEJSC_PO_PRZECINKU = 6


class Command(BaseCommand):
    help = "Liczy i zapisuje wektory zestawu pomiarowego RAG (wywołuje płatne API)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wymus",
            action="store_true",
            help="Nadpisz istniejący wzorzec bez pytania.",
        )

    def handle(self, *args, **opcje):
        if SCIEZKA_WZORCA.exists() and not opcje["wymus"]:
            raise CommandError(
                f"Wzorzec juz istnieje: {SCIEZKA_WZORCA}\n"
                "Nadpisanie go zmienia punkt odniesienia dla wszystkich pomiarow. "
                "Jesli naprawde tego chcesz, dodaj --wymus."
            )

        if not settings.OPENAI_API_KEY:
            raise CommandError("Brak OPENAI_API_KEY - nie ma czym policzyc wektorow.")

        from openai import OpenAI

        teksty = teksty_do_zamiany_na_wektory()
        self.stdout.write(f"Licze wektory dla {len(teksty)} tekstow...")

        klient = OpenAI(api_key=settings.OPENAI_API_KEY)
        odpowiedz = klient.embeddings.create(input=teksty, model=settings.OPENAI_EMBEDDING_MODEL)

        # Kolejnosc odpowiedzi z API odpowiada kolejnosci wejscia, ale
        # sprawdzamy to wprost: ciche przestawienie wektorow daloby wzorzec,
        # ktory wyglada poprawnie i mierzy bzdury.
        wektory = [wpis.embedding for wpis in sorted(odpowiedz.data, key=lambda w: w.index)]
        if len(wektory) != len(teksty):
            raise CommandError(f"API zwrocilo {len(wektory)} wektorow na {len(teksty)} tekstow.")

        zaokraglone = [[round(liczba, MIEJSC_PO_PRZECINKU) for liczba in w] for w in wektory]
        klucze_fragmentow = list(FRAGMENTY)
        granica = len(klucze_fragmentow)

        wzorzec = {
            "model": settings.OPENAI_EMBEDDING_MODEL,
            "wymiarow": len(wektory[0]),
            "fragmenty": dict(zip(klucze_fragmentow, zaokraglone[:granica], strict=True)),
            "pytania": {
                pytanie.tresc: wektor
                for pytanie, wektor in zip(PYTANIA, zaokraglone[granica:], strict=True)
            },
        }

        SCIEZKA_WZORCA.parent.mkdir(parents=True, exist_ok=True)
        SCIEZKA_WZORCA.write_text(json.dumps(wzorzec, ensure_ascii=False), encoding="utf-8")

        rozmiar = SCIEZKA_WZORCA.stat().st_size / 1024
        self.stdout.write(
            self.style.SUCCESS(
                f"Zapisano {SCIEZKA_WZORCA.name}: "
                f"{len(wzorzec['fragmenty'])} fragmentow, "
                f"{len(wzorzec['pytania'])} pytan, {rozmiar:.0f} kB"
            )
        )
        self.stdout.write(f"  zuzyte tokeny: {odpowiedz.usage.total_tokens}")
