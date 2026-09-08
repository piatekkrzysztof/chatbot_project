"""
Mierzy, jak model czatu zachowuje się na znanym korpusie.

Po co, skoro jest już `ocen_rag`
--------------------------------
`ocen_rag` mierzy wyszukiwanie i przy zmianie `OPENAI_CHAT_MODEL` pokaże co do
cyfry to samo - bo wektory liczy inny model. Rzecz, która zmienia się przy
podmianie modelu czatu, jest dokładnie tą, na którą do tej pory nie było miary.

Trzy liczby, w kolejności ważności
----------------------------------
0. **odmowy na uprzejmości** - ile powitań dostało znacznik. Jedyna dobra
   wartość to zero. Stoi przed resztą, bo jest widoczna gołym okiem: bot, który
   na „dzień dobry" odpowiada „nie udzielam informacji na ten temat", zniechęca
   odwiedzającego w pierwszym zdaniu i zakłada właścicielowi fałszywe
   zapytanie.
1. **odmowy trafne** - ile pytań spoza bazy wiedzy dostało `[BRAK_ODPOWIEDZI]`.
   Na tym znaczniku wisi propozycja kontaktu, zapytanie do właściciela, raport
   luk i alert o odmowach. Model, który przestaje go stawiać, nie psuje się
   głośno - po prostu zaczyna odpowiadać pewnym głosem z najbliższego
   fragmentu, a my przestajemy się o tym dowiadywać.
2. **odmowy fałszywe** - ile pytań POKRYTYCH dostało znacznik. Model zbyt
   ostrożny odmawia wiedzy, którą firma naprawdę ma.
3. **oparte na wiedzy** - ile odpowiedzi zawiera konkret z fragmentu.
   Bez tego model może przestać zmyślać, stając się zarazem bezużytecznym:
   „ceny znajdzie Pan w cenniku" nie jest ani odmową, ani odpowiedzią.

    python manage.py ocen_generowanie
    python manage.py ocen_generowanie --model gpt-4o-mini --model NOWY
    python manage.py ocen_generowanie --powtorzen 5

To kosztuje prawdziwe pieniądze: 19 pytań razy liczba powtórzeń, razy liczba
modeli. Komenda mówi, ile wywołań zrobi, zanim je zrobi.

Nic nie zostaje w bazie: korpus wjeżdża jako prawdziwe dokumenty i wycofuje się
razem z transakcją.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from rag.ocena.generowanie import niestabilne, ocen_generowanie, opisz_bledy
from rag.ocena.korpus import PYTANIA


class Command(BaseCommand):
    help = "Mierzy zachowanie modelu czatu na korpusie (wywołuje płatne API)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            action="append",
            dest="modele",
            metavar="NAZWA",
            help="Model do zmierzenia. Można podać wielokrotnie, żeby porównać.",
        )
        parser.add_argument(
            "--powtorzen",
            type=int,
            default=3,
            metavar="N",
            help=(
                "Ile razy zadać każde pytanie (domyślnie 3). Temperatura wynosi "
                f"{settings.OPENAI_TEMPERATURE}, więc jeden przebieg nie rozstrzyga."
            ),
        )
        parser.add_argument(
            "--bez-temperatury",
            action="store_true",
            help=(
                "Nie wysyłaj parametru temperature. Wymagane przez nowsze modele "
                "i jedyne ustawienie wspólne dla nich i dla gpt-4o-mini."
            ),
        )
        parser.add_argument(
            "--pokaz-odpowiedzi",
            action="store_true",
            help="Wypisz treść każdej odpowiedzi, nie tylko rozstrzygnięcie.",
        )

    def handle(self, *args, **opcje):
        if not settings.OPENAI_API_KEY:
            raise CommandError("Brak OPENAI_API_KEY - nie ma czym zapytać modelu.")
        if opcje["powtorzen"] < 1:
            raise CommandError("--powtorzen musi być dodatnie.")

        modele = opcje["modele"] or [settings.OPENAI_CHAT_MODEL]
        wywolan = len(PYTANIA) * opcje["powtorzen"] * len(modele)

        self.stdout.write(
            f"{len(PYTANIA)} pytan x {opcje['powtorzen']} powtorzen x {len(modele)} "
            f"model(e) = {wywolan} platnych wywolan API."
        )
        temperatura = None if opcje["bez_temperatury"] else ...
        opis_temp = (
            "domyslna modelu (parametr nie wysylany)"
            if opcje["bez_temperatury"]
            else settings.OPENAI_TEMPERATURE
        )
        self.stdout.write(f"Temperatura: {opis_temp}")
        self.stdout.write("")

        oceny = {}
        for model in modele:
            self.stdout.write(self.style.MIGRATE_HEADING(f"Model: {model}"))
            # Wycofanie transakcji zamiast sprzatania po sobie: korpus wjezdza
            # do bazy jako prawdziwe dokumenty, wiec bez tego komenda
            # diagnostyczna zostawialaby w bazie klienta wymyslony sklep
            # rowerowy - i to przy kazdym uruchomieniu.
            try:
                with transaction.atomic():
                    oceny[model] = ocen_generowanie(
                        model=model,
                        powtorzen=opcje["powtorzen"],
                        po_pytaniu=self._kropka,
                        temperatura=temperatura,
                    )
                    transaction.set_rollback(True)
            except Exception as blad:
                # Pojedynczy model, ktory odrzuca ustawienia, nie moze zabrac
                # wyniku pozostalym - a wlasnie po to sie je porownuje.
                self.stdout.write("")
                self.stdout.write(self.style.ERROR(f"  {model}: {str(blad)[:220]}"))
                self.stdout.write(
                    "  Sprawdz `manage.py sprawdz_model --model "
                    f"{model}` - to jedno wywolanie zamiast dziesiatek."
                )
                self.stdout.write("")
                continue
            self.stdout.write("")
            self._wypisz(oceny[model], opcje["pokaz_odpowiedzi"])
            self.stdout.write("")

        if len(modele) > 1:
            self._porownaj(oceny)

    def _kropka(self, odpowiedz):
        """Znak życia. Przebieg na dużym modelu trwa minutę."""
        self.stdout.write("." if odpowiedz.tokenow else "?", ending="")

    def _wypisz(self, ocena, pokaz_odpowiedzi):
        pudla = ocena.pytania_bez_fragmentow
        if pudla:
            # To mowi o WYSZUKIWANIU, nie o modelu, wiec stoi przed liczbami
            # modelu i jest z nich wylaczone. Model odmawia na tych pytaniach
            # slusznie: nic nie dostal.
            self.stdout.write(
                self.style.WARNING(
                    f"  Pudla wyszukiwania ({len(pudla)}): pytanie pokryte, ale zaden "
                    "fragment nie przeszedl progu."
                )
            )
            for tresc in pudla:
                self.stdout.write(f"    {tresc}")
            self.stdout.write(
                "  Te pytania sa wylaczone z liczb ponizej - mowia o progu, nie o modelu."
            )
            self.stdout.write("")

        self.stdout.write(
            f"  odmowy trafne      {ocena.odmowy_trafne:6.1%}   "
            "(pytania spoza bazy, ktore dostaly znacznik - im wiecej, tym lepiej)"
        )
        self.stdout.write(
            f"  odmowy falszywe    {ocena.odmowy_falszywe:6.1%}   "
            "(pytania pokryte, ktore dostaly znacznik - im mniej, tym lepiej)"
        )
        self.stdout.write(
            f"  odmowy na uprzejm. {ocena.uprzejmosci_odrzucone:6.1%}   "
            "(powitania, ktore dostaly znacznik - jedyna dobra wartosc to zero)"
        )
        self.stdout.write(
            f"  oparte na wiedzy   {ocena.oparte_na_wiedzy:6.1%}   "
            f"(odpowiedzi z konkretem z fragmentu, sprawdzalnych: "
            f"{ocena.sprawdzalnych_faktow})"
        )
        self.stdout.write("")
        self.stdout.write(
            f"  tokenow lacznie    {ocena.tokenow:>6,}   "
            f"({ocena.tokenow / len(ocena.odpowiedzi):.0f} na odpowiedz)"
        )
        self.stdout.write(f"  czas odpowiedzi    {ocena.sekund_srednio:6.2f} s   (srednio)")

        rozjazdy = niestabilne(ocena)
        if rozjazdy:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"  Niestabilne ({len(rozjazdy)}): model raz stawia znacznik, raz nie."
                )
            )
            self.stdout.write("  U prawdziwego odwiedzajacego zachowa sie na nich losowo.")
            for pytanie, odmow, ile in rozjazdy:
                self.stdout.write(f"    {odmow}/{ile} odmow  [{pytanie.grupa}] {pytanie.tresc}")

        bledy = opisz_bledy(ocena)
        if bledy:
            self.stdout.write("")
            self.stdout.write(f"  Do obejrzenia ({len(bledy)}):")
            for opis in dict.fromkeys(bledy):
                self.stdout.write(opis)

        if pokaz_odpowiedzi:
            self.stdout.write("")
            for odpowiedz in ocena.odpowiedzi:
                znak = "ODMOWA " if odpowiedz.odmowil else "odpowiedz"
                self.stdout.write(f"  [{znak}] {odpowiedz.pytanie.tresc}")
                self.stdout.write(f"      {odpowiedz.tresc[:160]}")

    def _porownaj(self, oceny):
        self.stdout.write(self.style.MIGRATE_HEADING("POROWNANIE"))
        self.stdout.write(
            f"{'model':<24} {'odm. trafne':>12} {'odm. falsz.':>12} "
            f"{'uprzejm.':>9} {'z wiedzy':>9} {'tokenow':>9} {'sekund':>7}"
        )
        for model, ocena in oceny.items():
            self.stdout.write(
                f"{model[:24]:<24} {ocena.odmowy_trafne:>11.1%} "
                f"{ocena.odmowy_falszywe:>11.1%} {ocena.uprzejmosci_odrzucone:>8.1%} "
                f"{ocena.oparte_na_wiedzy:>8.1%} "
                f"{ocena.tokenow:>9,} {ocena.sekund_srednio:>7.2f}"
            )
        self.stdout.write("")
        self.stdout.write(
            "Kolumna 'tokenow' to caly przebieg, wiec da sie ja przelozyc na koszt\n"
            "wprost z cennika. Uwaga: liczba tokenow wejsciowych jest ta sama dla\n"
            "kazdego modelu (ten sam prompt), rozni sie cena za token."
        )
        self.stdout.write("")
        self.stdout.write(
            "Korpus ma 19 pytan jednego wymyslonego sklepu. Wystarcza, zeby zobaczyc,\n"
            "ze model przestal stawiac znacznik. Nie wystarcza, zeby na tej podstawie\n"
            "orzec, ze jeden model jest ogolnie lepszy od drugiego."
        )
