"""
Wypisuje jakość wyszukiwania na zestawie pomiarowym.

To samo, co mierzy `rag/test_ocena.py`, ale w formie do czytania i z opcją
przemiatania progu. Test odpowiada „czy jest gorzej niż było"; ta komenda
odpowiada „jak jest i co by dało przesunięcie progu".

Nie kosztuje nic: liczy na zamrożonych wektorach z `rag/ocena/wzorzec.json`,
bez ani jednego wywołania API.

Uwaga o zakresie: korpus ma dziesięć fragmentów jednego wymyślonego sklepu.
Wystarcza, żeby wykryć regresję w wyszukiwaniu, ale NIE wystarcza, żeby na tej
podstawie ustawić próg produkcyjny - odległości zależą od konkretnych
dokumentów klienta. Do tego służy `zmierz_prog_rag`, które liczy rozkład na
żywej bazie wiedzy.

    python manage.py ocen_rag
    python manage.py ocen_rag --przemiataj
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from rag.ocena.miary import opisz_bledy
from rag.ocena.przebieg import ocen_na_wzorcu

PROGI_DO_PRZEMIATANIA = [0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25]


class Command(BaseCommand):
    help = "Mierzy jakosc wyszukiwania na zestawie pomiarowym (nic nie zmienia, nic nie kosztuje)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--przemiataj",
            action="store_true",
            help="Pokaz wymiane miedzy trafnoscia a cisza dla roznych progow.",
        )

    def handle(self, *args, **opcje):
        try:
            if opcje["przemiataj"]:
                self._przemiataj()
            else:
                self._pojedynczy_pomiar()
        except FileNotFoundError as brak:
            raise CommandError(str(brak)) from brak

    def _pojedynczy_pomiar(self):
        # Wycofanie transakcji zamiast sprzatania po sobie: korpus wjezdza do
        # bazy jako prawdziwe dokumenty, wiec bez tego komenda diagnostyczna
        # zostawialaby w bazie klienta wymyslona firme z cennikiem rowerow.
        with transaction.atomic():
            ocena, wyniki = ocen_na_wzorcu()
            transaction.set_rollback(True)

        self.stdout.write(f"Prog RAG_MAX_DISTANCE: {settings.RAG_MAX_DISTANCE}")
        self.stdout.write("")
        for wiersz in ocena.jako_wiersze():
            self.stdout.write("  " + wiersz)

        bledy = opisz_bledy(wyniki)
        if not bledy:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Wszystkie pytania rozstrzygniete poprawnie."))
            return

        self.stdout.write("")
        self.stdout.write(f"Do poprawy ({len(bledy)}):")
        for opis in bledy:
            self.stdout.write(opis)

    def _przemiataj(self):
        self.stdout.write(" prog | trafnosc | na 1. | MRR   | cisza")
        self.stdout.write("------+----------+-------+-------+------")

        for prog in PROGI_DO_PRZEMIATANIA:
            with transaction.atomic():
                ocena, _ = ocen_na_wzorcu(max_distance=prog)
                transaction.set_rollback(True)

            biezacy = " <- obecny" if prog == settings.RAG_MAX_DISTANCE else ""
            self.stdout.write(
                f" {prog:.2f} |  {ocena.trafnosc:6.1%} | {ocena.trafnosc_na_pierwszym:5.1%} "
                f"| {ocena.srednia_odwrotna_pozycja:.3f} | {ocena.cisza:5.1%}{biezacy}"
            )

        self.stdout.write("")
        self.stdout.write(
            "Trafnosc i cisza ida w przeciwne strony. Prog produkcyjny sprawdz "
            "na zywej bazie wiedzy komenda zmierz_prog_rag - dziesiec fragmentow "
            "wymyslonego sklepu to za malo, zeby go na tej podstawie ustawiac."
        )
