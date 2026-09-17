"""
Ile naprawdę kosztuje nas jeden klient.

Cennik obiecuje 2 000, 8 000 i 25 000 wiadomości miesięcznie za 149, 349 i 899
złotych. Żeby wiedzieć, czy to ma sens, trzeba znać koszt krańcowy jednej
wiadomości - a ten dotąd nie był nigdzie policzony. Bez niego cennik jest
zgadywaniem, które wygląda na decyzję.

Czego ten pomiar NIE wie dokładnie
----------------------------------
Logi zapisują `usage.total_tokens`, czyli wejście i wyjście razem. OpenAI
liczy je osobno i po różnych stawkach (wyjście zwykle kilkukrotnie drożej), więc
z jednej liczby nie da się odtworzyć rachunku.

Podział szacujemy z długości tekstów, które w logu są: prompt i odpowiedź.
Udział wyjścia to `znaki odpowiedzi / (znaki promptu + znaki odpowiedzi)`.
To przybliżenie - tokenizacja nie jest wprost proporcjonalna do znaków, a polski
tekst ma inny stosunek znaków do tokenów niż angielski. Przy stawkach
różniących się czterokrotnie błąd podziału o kilka punktów procentowych zmienia
wynik o kilka procent, nie o rząd wielkości: do decyzji cenowej wystarczy, do
faktury nie.

Właściwe rozwiązanie to zapisywanie `prompt_tokens` i `completion_tokens`
osobno - OpenAI zwraca oba w tej samej odpowiedzi, z której bierzemy dziś sumę.
Wtedy ten pomiar przestaje szacować cokolwiek. Do czasu tej zmiany wynik jest
oznaczony jako szacunek i tak należy go czytać.

Ceny podaje się z linii poleceń, bo zmieniają się częściej niż ten kod, a wpisana
na stałe stawka po cichu dezaktualizuje wynik. Domyślne pochodzą z cennika
gpt-4o-mini i text-embedding-3-small z września 2026 - sprawdź je przed użyciem.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.plans import PLANS
from chat.models import ChatMessage, PromptLog

MILION = 1_000_000
# Z pomiaru na produkcji: 2,7 kB tekstu na fragment. Tokenów jest mniej niż
# znaków - dla polskiego tekstu przyjmujemy trzy znaki na token.
ZNAKI_NA_TOKEN = 3


def rozklad_tokenow(wpisy):
    """
    Średni udział wyjścia w tokenach, oszacowany z długości tekstów.

    Wpisy bez odpowiedzi albo bez tokenów pomijamy: import historii z CSV
    zapisuje log z zerem, a wliczony do średniej zaniżałby koszt wiadomości,
    której model nigdy nie wygenerował.
    """
    znaki_promptu = 0
    znaki_odpowiedzi = 0
    tokeny = 0
    ile = 0
    for prompt, odpowiedz, tokens in wpisy:
        if not tokens or not odpowiedz:
            continue
        znaki_promptu += len(prompt or "")
        znaki_odpowiedzi += len(odpowiedz)
        tokeny += tokens
        ile += 1
    if not ile:
        return {"wiadomosci": 0, "tokenow": 0, "udzial_wyjscia": 0.0, "na_wiadomosc": 0.0}
    razem_znakow = znaki_promptu + znaki_odpowiedzi
    return {
        "wiadomosci": ile,
        "tokenow": tokeny,
        "udzial_wyjscia": znaki_odpowiedzi / razem_znakow if razem_znakow else 0.0,
        "na_wiadomosc": tokeny / ile,
    }


def koszt_wiadomosci(rozklad, ceny):
    """Koszt jednej wiadomości w złotych, przy podanych stawkach."""
    tokeny = rozklad["na_wiadomosc"]
    wyjscie = tokeny * rozklad["udzial_wyjscia"]
    wejscie = tokeny - wyjscie
    usd = (wejscie * ceny["wejscie"] + wyjscie * ceny["wyjscie"]) / MILION
    # Każde pytanie to dodatkowo jeden wektor pytania. Krótki, ale nie zerowy.
    usd += ceny["pytanie_tokenow"] * ceny["embedding"] / MILION
    return usd * ceny["kurs"]


def koszt_bazy_wiedzy(znakow, ceny):
    """Jednorazowy koszt policzenia wektorów dla bazy tej wielkości, w złotych."""
    tokeny = znakow / ZNAKI_NA_TOKEN
    return tokeny * ceny["embedding"] / MILION * ceny["kurs"]


def marza_planu(plan, koszt_jednej, ceny):
    """
    Ile zostaje z abonamentu, gdy klient wykorzysta limit wiadomości do końca.

    Liczone dla najgorszego przypadku, nie dla średniej: klient, który płaci za
    25 000 wiadomości i wysyła 300, jest zyskowny zawsze. Pytanie brzmi, czy
    pozostaje zyskowny ten, który bierze to, za co zapłacił.
    """
    koszt_wiadomosci_razem = plan.message_limit * koszt_jednej
    baza = koszt_bazy_wiedzy(plan.knowledge_base_mb * 1024 * 1024, ceny)
    return {
        "plan": plan.name,
        "cena": plan.price_pln,
        "limit": plan.message_limit,
        "koszt_wiadomosci": koszt_wiadomosci_razem,
        "koszt_bazy": baza,
        "zostaje": plan.price_pln - koszt_wiadomosci_razem,
        "udzial_kosztu": (koszt_wiadomosci_razem / plan.price_pln) if plan.price_pln else 0.0,
    }


class Command(BaseCommand):
    help = "Koszt krańcowy klienta w tokenach OpenAI, na podstawie logów zużycia."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--dni", type=int, default=30)
        parser.add_argument("--usd-wejscie", type=float, default=0.15)
        parser.add_argument("--usd-wyjscie", type=float, default=0.60)
        parser.add_argument("--usd-embedding", type=float, default=0.02)
        parser.add_argument("--kurs", type=float, default=4.0)

    def handle(self, *args, **options):
        if options["dni"] < 1:
            raise CommandError("--dni musi być dodatnie.")
        od = timezone.now() - timedelta(days=options["dni"])

        wpisy = PromptLog.objects.filter(created_at__gte=od).values_list(
            "prompt", "response", "tokens"
        )
        rozklad = rozklad_tokenow(wpisy)
        if not rozklad["wiadomosci"]:
            self.stdout.write(
                f"Brak wiadomości z modelu w ostatnich {options['dni']} dniach. "
                "Nie ma z czego liczyć kosztu."
            )
            return

        # Średnia długość pytania odwiedzającego - potrzebna do kosztu wektora
        # pytania, którego nigdzie nie logujemy.
        pytania = ChatMessage.objects.filter(timestamp__gte=od, sender="user").values_list(
            "message", flat=True
        )
        pytania = list(pytania)
        srednie_pytanie = sum(len(p or "") for p in pytania) / len(pytania) if pytania else 60

        ceny = {
            "wejscie": options["usd_wejscie"],
            "wyjscie": options["usd_wyjscie"],
            "embedding": options["usd_embedding"],
            "kurs": options["kurs"],
            "pytanie_tokenow": srednie_pytanie / ZNAKI_NA_TOKEN,
        }
        jedna = koszt_wiadomosci(rozklad, ceny)

        self.stdout.write(
            f"Koszt krańcowy klienta, z logów z ostatnich {options['dni']} dni.\n"
            f"Stawki: wejście {ceny['wejscie']} USD/mln, wyjście {ceny['wyjscie']} USD/mln, "
            f"embedding {ceny['embedding']} USD/mln, kurs {ceny['kurs']} PLN/USD.\n"
            "SZACUNEK: logi mają sumę tokenów, podział na wejście i wyjście "
            "odtworzony z długości tekstów.\n"
        )
        self.stdout.write(
            f"\nZmierzone: {rozklad['wiadomosci']} wiadomości, "
            f"{rozklad['tokenow']} tokenów razem, "
            f"{rozklad['na_wiadomosc']:.0f} tokenów na wiadomość, "
            f"udział wyjścia {100 * rozklad['udzial_wyjscia']:.0f}%."
        )
        self.stdout.write(f"Koszt jednej wiadomości: {jedna:.4f} zł\n")

        self.stdout.write("\nPrzy pełnym wykorzystaniu limitu planu:\n")
        for kod in PLANS:
            w = marza_planu(PLANS[kod], jedna, ceny)
            self.stdout.write(
                f"  {w['plan']:<6} {w['cena']:>4} zł/mies., limit {w['limit']:>6} wiad. "
                f"-> model {w['koszt_wiadomosci']:>7.2f} zł "
                f"({100 * w['udzial_kosztu']:.0f}% ceny), zostaje {w['zostaje']:>7.2f} zł"
            )
            self.stdout.write(
                f"         jednorazowo wektory pełnej bazy wiedzy: {w['koszt_bazy']:.2f} zł"
            )

        self.stdout.write(
            "\nCo nie jest tu policzone: hosting (stały, niezależny od liczby klientów), "
            "poczta, Stripe i czas pracy. To jest koszt krańcowy, nie pełny koszt usługi."
        )
