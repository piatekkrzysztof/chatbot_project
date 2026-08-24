"""
Mierzy, czy próg odległości dla wyszukiwania fragmentów jest dobrze ustawiony.

RAG_MAX_DISTANCE odcina fragmenty zbyt odległe od pytania. Wartość 1,15 była
dobrana pod stary podział dokumentów — krótkie, 500-znakowe kawałki mieszające
po kilka tematów. Po przejściu na fragmenty cięte po sekcjach rozkład
odległości jest inny: fragment o jednym temacie leży bliżej pytania z tego
tematu i dalej od pozostałych. Ten sam próg może więc teraz albo przepuszczać
śmieci, albo odcinać trafienia.

Zgadywać się tu nie da, bo odległości zależą od konkretnych dokumentów
klienta. Komenda pokazuje liczby: jak daleko leżą fragmenty przy pytaniach,
na które baza wiedzy odpowiada, i jak daleko przy pytaniach spoza niej.
Próg powinien przebiegać między tymi dwoma grupami.

Niczego nie zmienia — tylko liczy i wypisuje.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pgvector.django import L2Distance

from accounts.models import Tenant
from chat.models import PromptLog
from documents.models import DocumentChunk
from documents.utils.embedding_generator import get_client

# Pytania spoza jakiejkolwiek bazy wiedzy klienta. Służą za punkt odniesienia:
# ich odległości pokazują, gdzie zaczyna się "to na pewno nie pasuje".
PYTANIA_KONTROLNE = [
    "Jaka jest stolica Australii?",
    "Ile wynosi pierwiastek z dwustu pięćdziesięciu sześciu?",
    "Kto napisał Lalkę?",
    "Jak wymienić olej w silniku diesla?",
]

ILE_PYTAN_Z_HISTORII = 15


class Command(BaseCommand):
    help = "Mierzy rozkład odległości fragmentów dla pytań klienta (nic nie zmienia)."

    def add_arguments(self, parser):
        parser.add_argument("--firma", type=int, required=True, metavar="ID")
        parser.add_argument(
            "--pytanie", action="append", dest="pytania", metavar="TEKST",
            help="Dodatkowe pytanie do zmierzenia. Można podać wielokrotnie.",
        )

    def handle(self, *args, **opcje):
        try:
            tenant = Tenant.objects.get(pk=opcje["firma"])
        except Tenant.DoesNotExist:
            raise CommandError(f"Nie ma firmy o id {opcje['firma']}.")

        fragmentow = DocumentChunk.objects.filter(document__tenant=tenant).count()
        if not fragmentow:
            raise CommandError(f"Firma {tenant.name} nie ma żadnych fragmentów.")

        prog = settings.RAG_MAX_DISTANCE
        self.stdout.write(f"Firma: {tenant.name}   fragmentów: {fragmentow}   obecny próg: {prog}")
        self.stdout.write("")

        # Prawdziwe pytania odwiedzających, bez powtórzeń i bez rozmów testowych
        # Rozdzielamy po zapisanym źródle odpowiedzi. To istotne: historia
        # zawiera i pytania, na które baza odpowiada, i takie, na które nie —
        # liczenie z nich wspólnej granicy dawałoby próg zawyżony o te drugie.
        odpowiedziane, bez_pokrycia = [], []
        widziane = set()
        for tresc, zrodlo in (
            PromptLog.objects
            .filter(tenant=tenant)
            .exclude(conversation__source="test")
            .order_by("-created_at")
            .values_list("prompt", "source")
        ):
            klucz = " ".join((tresc or "").lower().split())
            if not klucz or klucz in widziane:
                continue
            widziane.add(klucz)
            (bez_pokrycia if zrodlo == "gpt" else odpowiedziane).append(tresc.strip())
            if len(widziane) >= ILE_PYTAN_Z_HISTORII:
                break

        # Pytania podane w wywołaniu nie mają zapisanego źródła — pokazujemy je
        # osobno, bo nie wiadomo, do której grupy należą.
        podane = opcje.get("pytania") or []

        klient = get_client(tenant)
        blisko_odpowiedziane = self._zmierz(
            klient, tenant, odpowiedziane, prog,
            "BOT ODPOWIEDZIAŁ Z BAZY — te muszą przechodzić",
        )
        blisko_bez_pokrycia = self._zmierz(
            klient, tenant, bez_pokrycia, prog,
            "BOT NIE ZNALAZŁ ODPOWIEDZI — te powinny być odcięte",
        )
        self._zmierz(klient, tenant, podane, prog, "PYTANIA PODANE W WYWOŁANIU")
        blisko_kontrolne = self._zmierz(
            klient, tenant, PYTANIA_KONTROLNE, prog,
            "PYTANIA KONTROLNE — spoza jakiejkolwiek bazy wiedzy",
        )

        self._podsumuj(blisko_odpowiedziane, blisko_bez_pokrycia, blisko_kontrolne, prog)

    def _zmierz(self, klient, tenant, pytania, prog, tytul):
        if not pytania:
            return []

        self.stdout.write(self.style.MIGRATE_HEADING(tytul))
        self.stdout.write(f"{'najbliżej':>10} {'2.':>7} {'3.':>7}  {'przejdzie':>9}  pytanie / trafiony fragment")

        najblizsze = []
        for pytanie in pytania:
            wektor = klient.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL, input=pytanie,
            ).data[0].embedding

            trafienia = list(
                DocumentChunk.objects
                .filter(document__tenant=tenant)
                .annotate(distance=L2Distance("embedding", wektor))
                .order_by("distance")[:5]
            )
            odleglosci = [t.distance for t in trafienia]
            if not odleglosci:
                continue

            najblizsze.append((odleglosci[0], pytanie))
            ile_przejdzie = sum(1 for d in odleglosci if d <= prog)
            kolumny = [f"{d:.3f}" for d in (odleglosci + [None, None, None])[:3] if d is not None]
            while len(kolumny) < 3:
                kolumny.append("  —  ")

            self.stdout.write(
                f"{kolumny[0]:>10} {kolumny[1]:>7} {kolumny[2]:>7}  {ile_przejdzie:>9}  {pytanie[:58]}"
            )
            self.stdout.write(f"{'':>38}  └ {trafienia[0].content[:70].replace(chr(10), ' ')}")

        self.stdout.write("")
        return najblizsze

    def _podsumuj(self, odpowiedziane, bez_pokrycia, kontrolne, prog):
        self.stdout.write(self.style.MIGRATE_HEADING("PODSUMOWANIE"))

        def opis(nazwa, pary):
            """`pary` to (odległość, pytanie) — treść potrzebna przy nakładaniu grup."""
            if not pary:
                self.stdout.write(f"  {nazwa}: brak danych")
                return None
            uporzadkowane = sorted(pary)
            srodek = uporzadkowane[len(uporzadkowane) // 2][0]
            self.stdout.write(
                f"  {nazwa}: najmniejsza {uporzadkowane[0][0]:.3f}   "
                f"środkowa {srodek:.3f}   największa {uporzadkowane[-1][0]:.3f}"
            )
            return uporzadkowane

        z_bazy = opis("odpowiedziane z bazy ", odpowiedziane)
        bez = opis("bez pokrycia         ", bez_pokrycia)
        kontrola = opis("kontrolne            ", kontrolne)

        self.stdout.write("")
        if not z_bazy:
            self.stdout.write(
                "  Brak pytań odpowiedzianych z bazy — nie ma z czego wyznaczyć dolnej\n"
                "  granicy. Zadaj kilka pytań przez zakładkę Test bota i powtórz pomiar."
            )
        else:
            # Górna granica: to, co ma zostać odcięte. Bierzemy najbliższe
            # z pytań bez pokrycia, a gdy takich nie ma — z kontrolnych.
            odciac = sorted((bez or []) + (kontrola or []))
            najdalsze_trafne = z_bazy[-1][0]

            if odciac and odciac[0][0] > najdalsze_trafne:
                sugestia = (najdalsze_trafne + odciac[0][0]) / 2
                ocena = self.style.SUCCESS if abs(sugestia - prog) > 0.03 else self.style.NOTICE
                self.stdout.write(ocena(
                    f"  Próg rozdzielający grupy: {sugestia:.2f}   (obecnie {prog})"
                ))
            elif odciac:
                granica = odciac[0][0]
                # Nazywamy sporne wpisy, zamiast zostawiać sam werdykt. Zwykle
                # nie jest to wina progu, tylko etykiet: pytania sprzed poprawki
                # rozpoznawania odmowy siedzą w grupie „odpowiedziane z bazy",
                # choć bot wcale na nie nie odpowiedział. Ocena zajmuje chwilę,
                # o ile w ogóle widać, które są sporne.
                sporne = [(d, p) for d, p in z_bazy if d >= granica]
                self.stdout.write(self.style.WARNING(
                    f"  Grupy się nakładają: trafne sięgają {najdalsze_trafne:.3f}, "
                    f"a odcinane zaczynają się od {granica:.3f}."
                ))
                self.stdout.write("")
                self.stdout.write(
                    "  Sporne — oznaczone jako odpowiedziane z bazy, ale leżące dalej\n"
                    "  niż pierwsze z odcinanych. Przeczytaj i oceń, czy firma naprawdę\n"
                    "  na nie odpowiada:"
                )
                for odleglosc, pytanie in sporne:
                    self.stdout.write(f"      {odleglosc:.3f}  {pytanie[:64]}")
                self.stdout.write("")
                self.stdout.write(
                    f"  Jeśli to pytania spoza oferty, granica biegnie poniżej {granica:.3f} —\n"
                    "  pomiń je i policz z pozostałych. Jeśli naprawdę są pokryte, problem\n"
                    "  leży w treści dokumentów albo w podziale na fragmenty, nie w progu."
                )

        self.stdout.write("")
        self.stdout.write(
            "  UWAGA: wpisy sprzed poprawki rozpoznawania odmowy mają błędne źródło\n"
            "  (wszystko szło jako 'document'), więc grupy mogą być pomieszane.\n"
            "  Miarodajne są pytania zadane po tamtej zmianie."
        )
        self.stdout.write("  Nic nie zostało zmienione. Próg ustawia zmienna RAG_MAX_DISTANCE.")
