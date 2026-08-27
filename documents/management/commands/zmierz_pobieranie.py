"""
Porównuje, ile treści da się wyciągnąć ze strony klienta przy różnych
ustawieniach ekstrakcji.

Powstało z obserwacji na produkcji: strona główna agencji dała 257 znaków,
"/o-nas" 735, "/blog" 256 — przy "/cennik", który dał kilka tysięcy. Bot
praktycznie nie zna tych podstron, a w panelu widnieje przy nich zielony
status "gotowe".

Podejrzenie pada na `trafilatura`: to biblioteka do wyciągania treści
ARTYKUŁÓW, dobra w odsiewaniu nawigacji i obudowy wokół tekstu ciągłego.
Strona sprzedażowa złożona z kilkunastu krótkich sekcji marketingowych nie
wygląda dla niej jak artykuł, więc większość może uznawać za obudowę.
Do tego wołamy ją z `include_tables=False`, co wycina cenniki i zestawienia.

Komenda niczego nie zmienia. Pobiera stronę raz i przepuszcza przez kilka
wariantów ustawień, żeby dało się zobaczyć różnicę w liczbach, zanim
cokolwiek poprawimy w kodzie.
"""

import re

import trafilatura
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Tenant
from documents.models import Document

# Wariant „obecny" musi dokładnie odpowiadać temu, co robi
# documents/website_import.py:fetch_text_from_url — inaczej porównanie
# nie mówi nic o rzeczywistości.
WARIANTY = {
    "obecny": dict(include_comments=False, include_tables=False, include_formatting=False),
    "+tabele": dict(include_comments=False, include_tables=True, include_formatting=False),
    "+odzysk": dict(
        include_comments=False, include_tables=True, include_formatting=False, favor_recall=True
    ),
    "+odzysk+struktura": dict(
        include_comments=False, include_tables=True, include_formatting=True, favor_recall=True
    ),
    # Dwa warianty spoza logiki „wyciągnij artykuł". html2txt zamienia całą
    # stronę na tekst, bez oceniania, co jest treścią. „bez obudowy" robi to
    # samo, ale najpierw odcina nawigację, nagłówek i stopkę — czyli to,
    # co powtarza się na każdej podstronie.
    "html2txt": {},
    "bez obudowy": {},
}


# Obudowa strony: powtarza się na każdej podstronie, więc wciągnięta do bazy
# wiedzy tworzy dziesiątki niemal identycznych fragmentów pasujących „po trochu"
# do wszystkiego. Dokładnie ten problem miała sekcja „Kontakt / Porozmawiajmy".
OBUDOWA = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]


def bez_obudowy(html):
    """Widoczny tekst po odjęciu nawigacji, nagłówka i stopki."""
    zupa = BeautifulSoup(html, "html.parser")
    for znacznik in zupa(OBUDOWA):
        znacznik.decompose()
    tekst = zupa.get_text("\n")
    # Puste wiersze zbite do jednego — zachowujemy akapity, bo na nich opiera
    # się podział na fragmenty
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", tekst)).strip()


def tekst_widoczny(html):
    """
    Wszystko, co użytkownik zobaczyłby na stronie — bez skryptów i styli.

    To górna granica tego, co ekstrakcja mogłaby wyciągnąć. Zawiera też
    nawigację i stopkę, więc nie jest celem samym w sobie; służy za miarę,
    ile treści w ogóle jest na stronie.
    """
    zupa = BeautifulSoup(html, "html.parser")
    for znacznik in zupa(["script", "style", "noscript"]):
        znacznik.decompose()
    return re.sub(r"\s+", " ", zupa.get_text(" ")).strip()


class Command(BaseCommand):
    help = "Porównuje warianty ekstrakcji treści ze stron (nic nie zmienia)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--firma", type=int, metavar="ID", help="Weź adresy podstron zapisanych dla tej firmy."
        )
        parser.add_argument(
            "--url",
            action="append",
            dest="adresy",
            metavar="ADRES",
            help="Konkretny adres. Można podać wielokrotnie.",
        )
        parser.add_argument(
            "--pokaz",
            action="store_true",
            help="Wypisz też początek tego, co wyciąga najlepszy wariant.",
        )

    def handle(self, *args, **opcje):
        adresy = list(opcje.get("adresy") or [])

        if opcje.get("firma"):
            if not Tenant.objects.filter(pk=opcje["firma"]).exists():
                raise CommandError(f"Nie ma firmy o id {opcje['firma']}.")
            adresy += list(
                Document.objects.filter(tenant_id=opcje["firma"], source="website")
                .exclude(source_url="")
                .order_by("name")
                .values_list("source_url", flat=True)
            )

        if not adresy:
            raise CommandError("Podaj --url albo --firma.")

        naglowek = f"{'adres':<44}{'widoczny':>10}"
        for nazwa in WARIANTY:
            naglowek += f"{nazwa:>18}"
        self.stdout.write(naglowek)
        self.stdout.write("-" * len(naglowek))

        zyski = []
        for adres in adresy:
            pobrane = trafilatura.fetch_url(adres)
            if not pobrane:
                self.stdout.write(f"{adres[:43]:<44}{'NIE POBRANO':>10}")
                continue

            widoczny = len(tekst_widoczny(pobrane))
            wiersz = f"{adres[-43:]:<44}{widoczny:>10}"
            wyniki = {}
            for nazwa, ustawienia in WARIANTY.items():
                if nazwa == "html2txt":
                    tekst = trafilatura.html2txt(pobrane) or ""
                elif nazwa == "bez obudowy":
                    tekst = bez_obudowy(pobrane)
                else:
                    tekst = trafilatura.extract(pobrane, **ustawienia) or ""
                wyniki[nazwa] = tekst
                udzial = (len(tekst) / widoczny * 100) if widoczny else 0
                wiersz += f"{len(tekst):>11} {udzial:>4.0f}%"
            self.stdout.write(wiersz)

            obecny, najlepszy_nazwa = (
                len(wyniki["obecny"]),
                max(wyniki, key=lambda n: len(wyniki[n])),
            )
            zyski.append((adres, obecny, len(wyniki[najlepszy_nazwa]), najlepszy_nazwa))

            if opcje["pokaz"]:
                self.stdout.write(f"    najlepszy wariant: {najlepszy_nazwa}")
                self.stdout.write(f"    {wyniki[najlepszy_nazwa][:300]!r}")
                self.stdout.write("")

        self.stdout.write("")
        self.stdout.write("PODSUMOWANIE")
        razem_teraz = sum(o for _, o, _, _ in zyski)
        razem_najlepiej = sum(n for _, _, n, _ in zyski)
        self.stdout.write(f"  łącznie teraz:      {razem_teraz} znaków")
        self.stdout.write(f"  łącznie najlepiej:  {razem_najlepiej} znaków")
        if razem_teraz:
            self.stdout.write(f"  różnica:            {razem_najlepiej / razem_teraz:.1f}×")

        najgorsze = sorted(zyski, key=lambda z: (z[1] / z[2]) if z[2] else 1)[:5]
        if najgorsze:
            self.stdout.write("")
            self.stdout.write("  Podstrony, na których traci się najwięcej:")
            for adres, teraz, najlepiej, nazwa in najgorsze:
                if najlepiej > teraz:
                    self.stdout.write(f"    {teraz:>6} -> {najlepiej:>6} ({nazwa})   {adres[-52:]}")

        self.stdout.write("")
        self.stdout.write("  Nic nie zostało zmienione ani zapisane.")
