"""
Czy ten model przyjmie nasze ustawienia. Jedno wywołanie, przed wdrożeniem.

Po co osobna komenda
--------------------
Podmiana `OPENAI_CHAT_MODEL` na model, który odrzuca któryś z wysyłanych
parametrów, kończy się błędem 400 przy KAŻDYM pytaniu. `process_chat_message`
łapie wyjątek i oddaje komunikat awaryjny, więc bot odpowiada „coś poszło nie
tak" wszystkim klientom naraz.

I nic tego nie zgłasza. Fragmenty z wyszukiwania wracają normalnie, więc wpis
w PromptLog idzie ze źródłem „document"; alert o odmowach nie widzi wzrostu,
alert o ciszy nie widzi ciszy - rozmowy przecież są. Dowiedziałby się o tym
klient.

Ta komenda zamienia tę awarię w jedno zdanie w konsoli, za jedno wywołanie API.

    python manage.py sprawdz_model
    python manage.py sprawdz_model --model gpt-5.6-luna

Czego NIE sprawdza: jakości odpowiedzi. Od tego jest `ocen_generowanie`.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from api.utils.chat_engine import get_client, parametry_modelu

PROBA = [{"role": "user", "content": "Odpowiedz jednym slowem: OK."}]


class Command(BaseCommand):
    help = "Sprawdza, czy model przyjmuje obecne ustawienia (jedno wywołanie API)."

    def add_arguments(self, parser):
        parser.add_argument("--model", metavar="NAZWA", help="Domyślnie OPENAI_CHAT_MODEL.")

    def handle(self, *args, **opcje):
        model = opcje.get("model") or settings.OPENAI_CHAT_MODEL
        parametry = parametry_modelu()

        self.stdout.write(f"Model:      {model}")
        self.stdout.write(f"Parametry:  {parametry}")
        self.stdout.write("")

        try:
            odpowiedz = get_client().chat.completions.create(
                model=model, messages=PROBA, **parametry
            )
        except Exception as blad:
            self._wyjasnij(model, blad)
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"DZIALA. Model przyjal ustawienia i odpowiedzial "
                f"({odpowiedz.usage.total_tokens} tokenow)."
            )
        )
        self.stdout.write("")
        self.stdout.write(
            "To znaczy tylko, ze wywolanie przechodzi. Czy model dobrze stawia\n"
            "znacznik [BRAK_ODPOWIEDZI], mowi `manage.py ocen_generowanie`."
        )

    def _wyjasnij(self, model, blad):
        tresc = str(blad)
        self.stdout.write(self.style.ERROR(f"NIE DZIALA. {model} odrzucil te ustawienia."))
        self.stdout.write("")
        self.stdout.write(tresc[:400])
        self.stdout.write("")

        # Podpowiedz zamiast samego bledu z API. Komunikat OpenAI mowi, co jest
        # nie tak z zadaniem, i nie mowi, ktora zmienna srodowiskowa to ustawia
        # - a o to wlasnie pyta ktos, kto stoi przed wdrozeniem.
        if "temperature" in tresc:
            self.stdout.write(
                self.style.WARNING(
                    "Ten model przyjmuje tylko domyslna temperature.\n"
                    "  Wyczysc OPENAI_TEMPERATURE (pusta wartosc = nie wysylamy parametru).\n"
                    "  UWAGA: przy domyslnej temperaturze model chetniej uzupelnia luki\n"
                    "  wlasnymi domyslami. Przemierz `ocen_generowanie` przed wdrozeniem."
                )
            )
        elif "max_tokens" in tresc:
            self.stdout.write(
                self.style.WARNING(
                    "Kod wysyla max_completion_tokens, wiec ten blad nie powinien wystapic.\n"
                    "  Sprawdz, czy api/utils/chat_engine.py uzywa parametry_modelu()."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Nieznana niezgodnosc. Nie wdrazaj tego modelu, dopoki ta komenda\n"
                    "  nie przejdzie - w produkcji ten sam blad dostanie kazde pytanie."
                )
            )
