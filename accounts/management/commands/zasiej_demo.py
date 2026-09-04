"""
Zakłada firmę demonstracyjną z realistycznymi danymi.

Po co: README obiecuje „działające demo", a panel bez danych pokazuje same
zera i puste stany — czyli dokładnie nie to, co produkt robi. Ta komenda
wypełnia go ruchem, który wygląda jak miesiąc pracy prawdziwego warsztatu.

Dwie rzeczy, na których zależy najbardziej:

1. Nie woła OpenAI. Wektory są losowe, ale poprawnego wymiaru — wyszukiwanie
   działa mechanicznie, tylko trafia bez sensu. Dzięki temu obcy developer
   zasieje projekt bez klucza API, a klucz jest potrzebny dopiero wtedy, gdy
   chce porozmawiać z botem.

2. Konto demo ma rolę `viewer`, nie `owner`. IsOwnerOrEmployee jej nie
   przepuszcza, więc zwiedzający obejrzy rozmowy, zapytania i statystyki,
   ale nie wgra dokumentu, nie zmieni widgetu i nic nie skasuje.

Idempotentna: powtórzone uruchomienie nie dubluje danych, bo najpierw kasuje
poprzednią zawartość tej firmy (nie dotykając żadnej innej).
"""

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser, Subscription, Tenant, UserRole
from chat.models import (
    FAQ,
    ChatMessage,
    ContactRequest,
    Conversation,
    PromptLog,
)
from documents.models import Document, DocumentChunk
from documents.utils.fragmenty import podziel_na_fragmenty

NAZWA_FIRMY = "Rowerownia Krakowska (DEMO)"
WYMIAR_WEKTORA = 1536

FAQ_DEMO = [
    (
        "Jakie macie godziny otwarcia?",
        "Poniedziałek–piątek 9:00–18:00, sobota 10:00–14:00. W niedziele zamknięte.",
    ),
    (
        "Ile kosztuje przegląd roweru?",
        "Przegląd podstawowy 120 zł, rozszerzony 220 zł. Rower elektryczny +60 zł "
        "za diagnostykę układu wspomagania.",
    ),
    (
        "Czy naprawiacie rowery elektryczne?",
        "Tak, serwisujemy napędy Bosch, Shimano Steps i Bafang. Nie otwieramy "
        "ogniw akumulatora — przy usterce baterii kierujemy do autoryzowanego serwisu.",
    ),
    (
        "Jak długo czeka się na naprawę?",
        "Drobne naprawy tego samego dnia. Przegląd 2–3 dni robocze, w sezonie "
        "(kwiecień–czerwiec) do 5 dni.",
    ),
    (
        "Czy trzeba się umawiać?",
        "Na przegląd tak, telefonicznie lub mailem. Drobne naprawy przyjmujemy "
        "od ręki, jeśli akurat jest wolne stanowisko.",
    ),
    (
        "Czy mogę zostawić rower na przechowanie na zimę?",
        "Tak, przechowanie sezonowe 180 zł za sezon, w cenie przegląd na start sezonu.",
    ),
]

# Treść dokumentów demo.
#
# Wcześniej stał tu wypełniacz ("x" razy N) i to był cichy błąd. Fragmenty
# powstają z `document.content`, więc `przelicz_fragmenty` - komenda, do której
# odsyła komunikat na końcu tego zasiewu - liczyła prawdziwe wektory
# BEZSENSOWNEGO tekstu. Demo na produkcji miało przez to bazę wiedzy, z której
# nie dawało się wyciągnąć ani jednego zdania: najbliższy fragment leżał 1,010
# od pytania przy progu 1,0, więc nic nigdy nie przechodziło. Bot odpowiadał
# wyłącznie z FAQ i wyglądało to na działające demo.
#
# Treść jest napisana pod dzielnik z documents/utils/fragmenty.py: krótkie
# wiersze bez kropki na końcu są rozpoznawane jako nagłówki sekcji i wędrują
# z każdym fragmentem tej sekcji.
#
# Świadomie NIE opisuje: rowerów używanych, odbioru roweru z domu, faktur
# z odroczonym terminem ani rowerów zastępczych. To są pytania z
# PYTANIA_BEZ_POKRYCIA - panel ma pokazywać także lukę w bazie wiedzy,
# a nie same sukcesy. Dopisanie ich tutaj zepsułoby tamtą część demo.

CENNIK_DEMO = """Cennik usług serwisowych

Przeglądy okresowe
Przegląd podstawowy kosztuje 120 zł. Obejmuje regulację hamulców i przerzutek,
centrowanie kół, kontrolę ciśnienia w oponach, smarowanie napędu oraz kontrolę
dokręcenia śrub.

Przegląd rozszerzony kosztuje 220 zł. Dodatkowo czyścimy i smarujemy napęd
w kąpieli ultradźwiękowej, sprawdzamy zużycie kasety i łańcucha miernikiem
oraz przeglądamy amortyzator i sterów.

Rower elektryczny to dopłata 60 zł do każdego przeglądu. W tej cenie mieści się
diagnostyka układu wspomagania i odczyt błędów ze sterownika.

Naprawy pojedyncze
Wymiana dętki kosztuje 25 zł, opony 35 zł.
Wymiana łańcucha kosztuje 80 zł plus cena części.
Centrowanie pojedynczego koła kosztuje 60 zł.
Wymiana klocków hamulcowych kosztuje 40 zł za koło.
Wymiana linek i pancerzy kosztuje 50 zł za komplet.
Regulacja przerzutek kosztuje 45 zł.

Ceny nie obejmują części. Przed naprawą przekraczającą 200 zł dzwonimy
z wyceną i czekamy na zgodę.

Pakiety sezonowe
Przygotowanie roweru do sezonu kosztuje 180 zł. Obejmuje przegląd podstawowy,
wymianę smaru w piastach i sprawdzenie ogumienia po zimie.

Przygotowanie do zimy kosztuje 150 zł: mycie, konserwacja napędu preparatem
przeciw korozji i kontrola hamulców przed okresem soli na drogach.

Koło i ogumienie
Budowa koła od zera kosztuje 180 zł za sztukę plus części.
Wymiana szprychy z centrowaniem kosztuje 45 zł.
Uszczelnienie opony bezdętkowej kosztuje 55 zł za koło.

Zapłata
Za naprawę płaci się przy odbiorze. Przyjmujemy gotówkę, kartę i BLIK.
Na życzenie wystawiamy paragon albo fakturę z NIP-em.
"""

SERWIS_DEMO = """Zakres serwisu i naprawy

Co serwisujemy
Naprawiamy rowery miejskie, górskie, szosowe, gravelowe i dziecięce.
Serwisujemy rowery elektryczne z napędami Bosch, Shimano Steps i Bafang.

Nie otwieramy ogniw akumulatora. Przy usterce baterii kierujemy do
autoryzowanego serwisu producenta - to naprawa objęta osobnymi przepisami
bezpieczeństwa i wymaga uprawnień, których nie mamy.

Gwarancja na naprawę
Na wykonaną usługę dajemy 3 miesiące gwarancji. Gwarancja obejmuje robociznę
i wymienione przez nas części, nie obejmuje zużycia eksploatacyjnego.

Zakres zlecenia
Spisujemy usterkę przy przyjęciu i wydajemy potwierdzenie z numerem zlecenia.
O gotowości informujemy SMS-em na podany numer.

Jeśli w trakcie naprawy znajdziemy usterkę, o której nie było mowy przy
przyjęciu, dzwonimy przed jej naprawą. Nie robimy niczego ponad zlecenie
bez zgody właściciela roweru.

Części
Pracujemy na częściach Shimano, SRAM, Continental i Schwalbe. Jeśli klient
przyniesie własne części, montujemy je - ale gwarancją obejmujemy wtedy
wyłącznie robociznę.

Rowery dziecięce
Serwisujemy rowery dziecięce od 12 cali. Przegląd roweru dziecięcego kosztuje
70 zł i obejmuje regulację hamulców, kontrolę kół i wysokość siodła.
"""

#: Terminy dostaly wlasna podstrone, a nie sekcje w dokumencie o wszystkim.
#:
#: Wczesniej "Jak dlugo trwa przeglad w sezonie?" wypadalo 0,010 za progiem,
#: mimo ze tresc odpowiadala na nie wprost. Powod nie byl w slowach, tylko
#: w rozcienczeniu: sekcja o terminach dzielila fragment z gwarancja, czesciami
#: i rowerami dzieciecymi, wiec wektor fragmentu byl srednia z czterech
#: tematow. Osobna, krotka podstrona daje fragment o jednym temacie - i tak
#: samo wygladaja prawdziwe witryny klientow.
TERMINY_DEMO = """Terminy realizacji

Ile trwa przegląd
Przegląd trwa 2-3 dni robocze poza sezonem.

Przegląd w sezonie trwa dłużej. Sezon to kwiecień, maj i czerwiec - czas
oczekiwania na przegląd wydłuża się wtedy do 5-7 dni roboczych.

W sezonie warto umówić się telefonicznie z wyprzedzeniem. Rower przyjęty
na umówiony termin czeka w kolejce krócej.

Drobne naprawy
Wymianę dętki, regulację hamulca czy dokręcenie kierownicy robimy tego samego
dnia i zwykle bez wcześniejszych zapisów. Wystarczy przyjść w godzinach pracy
warsztatu.

Naprawy większe
Wymiana napędu, budowa koła i serwis amortyzatora zajmują 3-5 dni roboczych,
a w sezonie do 8 dni. Termin podajemy przy przyjęciu roweru.
"""

KONTAKT_DEMO = """Kontakt i godziny otwarcia

Godziny otwarcia
Poniedziałek-piątek 9:00-18:00.
Sobota 10:00-14:00.
W niedziele nieczynne.

W okresie od listopada do lutego w soboty zamykamy o 13:00.

Adres
Rowerownia Krakowska, ulica Wielicka 42, 30-552 Kraków.
Wejście od podwórza, na miejscu jest parking dla rowerów.

Telefon i poczta
Telefon: 12 345 67 89, czynny w godzinach pracy warsztatu.
Poczta: serwis@rowerownia-demo.pl - odpowiadamy w ciągu jednego dnia roboczego.

Płatności
Przyjmujemy gotówkę, karty płatnicze i BLIK.
"""

#: Adres, nazwa i treść. `znakow_na_stronie` liczymy z treści, zamiast wpisywać
#: wymyśloną liczbę - inaczej panel pokazywałby rozmiar bazy wiedzy, który nie
#: ma pokrycia w tym, co w niej faktycznie jest.
DOKUMENTY_DEMO = [
    ("https://rowerownia-demo.pl/cennik", "Cennik usług serwisowych", CENNIK_DEMO),
    ("https://rowerownia-demo.pl/serwis", "Zakres serwisu i naprawy", SERWIS_DEMO),
    ("https://rowerownia-demo.pl/terminy", "Terminy realizacji", TERMINY_DEMO),
    ("https://rowerownia-demo.pl/kontakt", "Kontakt i godziny otwarcia", KONTAKT_DEMO),
]

# Pytania odwiedzających. Część trafia w wiedzę, część nie — bo panel ma
# pokazywać także lukę w bazie, a nie wyłącznie sukcesy.
PYTANIA_ZNANE = [
    ("Ile kosztuje przegląd?", "document"),
    ("Do której jesteście otwarci w sobotę?", "faq"),
    ("Naprawiacie rowery elektryczne?", "faq"),
    ("Jak długo trwa przegląd w sezonie?", "document"),
    ("Czy muszę się umawiać na naprawę dętki?", "faq"),
    ("Ile kosztuje serwis roweru elektrycznego?", "document"),
    ("Przechowujecie rowery przez zimę?", "faq"),
    ("Czy robicie centrowanie kół?", "document"),
]
PYTANIA_BEZ_POKRYCIA = [
    "Czy sprzedajecie rowery używane?",
    "Możecie odebrać rower z domu?",
    "Wystawiacie faktury na firmę z odroczonym terminem?",
    "Czy macie rowery zastępcze na czas naprawy?",
]

ODPOWIEDZ_BRAK = (
    "Nie mam tej informacji w materiałach firmy. Zostaw kontakt, a odezwiemy się z odpowiedzią."
)

KONTAKTY_DEMO = [
    ("Marta Zielińska", "m.zielinska@example.com", "Pytanie o rower zastępczy"),
    ("", "606 100 200", "Prosi o wycenę serwisu e-bike"),
    ("Tomasz Bąk", "t.bak@example.com", "Faktura z odroczonym terminem"),
    ("", "512 340 990", ""),
    ("Anna Wrona", "anna.wrona@example.com", "Odbiór roweru z domu"),
]


class Command(BaseCommand):
    help = "Zakłada firmę demonstracyjną z realistycznymi danymi (bez wywołań OpenAI)."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="demo@agencjasm-art.pl", help="Login konta demo")
        parser.add_argument("--haslo", default="demo", help="Hasło konta demo")
        parser.add_argument("--dni", type=int, default=30, help="Na ile dni wstecz rozłożyć ruch")
        parser.add_argument("--usun", action="store_true", help="Skasuj firmę demo i wyjdź")

    def handle(self, *args, **opcje):
        # Ziarno na stałe: dwa uruchomienia dają ten sam panel, więc zrzuty
        # w README nie rozjeżdżają się z tym, co zobaczy zwiedzający.
        losowy = random.Random(20260825)

        if opcje["usun"]:
            usuniete, _ = Tenant.objects.filter(name=NAZWA_FIRMY).delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Skasowano firmę demo ({usuniete} obiektów)."
                    if usuniete
                    else "Nie było czego kasować."
                )
            )
            return

        with transaction.atomic():
            firma = self._firma()
            self._wyczysc(firma)
            uzytkownik = self._konto(firma, opcje["email"], opcje["haslo"])
            self._subskrypcja(firma)
            self._dokumenty(firma, losowy)
            self._faq(firma)
            rozmow, wiadomosci = self._ruch(firma, opcje["dni"], losowy)
            self._zapytania(firma, losowy)

        self.stdout.write(self.style.SUCCESS("\nFirma demo gotowa."))
        self.stdout.write(f"  Firma        : {firma.name}")
        self.stdout.write(f"  Login        : {uzytkownik.username}")
        self.stdout.write(f"  Hasło        : {opcje['haslo']}")
        self.stdout.write("  Rola         : viewer (tylko odczyt)")
        self.stdout.write(f"  Klucz widgetu: {firma.api_key}")
        self.stdout.write(
            f"  Zasiane      : {rozmow} rozmów, {wiadomosci} wiadomości, "
            f"{len(FAQ_DEMO)} FAQ, {len(DOKUMENTY_DEMO)} dokumenty"
        )
        self.stdout.write(
            "\n  Wektory są losowe — wyszukiwanie działa mechanicznie, ale trafia\n"
            "  bez sensu. Żeby bot odpowiadał z sensem, ustaw OPENAI_API_KEY\n"
            "  i przelicz fragmenty: manage.py przelicz_fragmenty --wykonaj\n"
        )

    # ─── składowe ───

    def _firma(self):
        firma, _ = Tenant.objects.get_or_create(
            name=NAZWA_FIRMY,
            defaults={"owner_email": "demo@agencjasm-art.pl"},
        )
        firma.widget_title = "Rowerownia"
        firma.widget_welcome_message = (
            "Cześć! Pytaj o ceny, terminy i zakres serwisu — odpowiem od razu, "
            "na podstawie naszego cennika."
        )
        # Bez opisu działalności pulpit wita zwiedzającego ostrzeżeniem
        # „uzupełnij bazę" — czyli demo otwiera się listą braków zamiast
        # produktem w stanie gotowym.
        firma.gpt_prompt = (
            "Jesteś asystentem serwisu rowerowego Rowerownia Krakowska. "
            "Odpowiadasz na pytania o ceny, terminy i zakres napraw wyłącznie "
            "na podstawie materiałów firmy. Gdy czegoś nie wiesz, mówisz to "
            "wprost i proponujesz zostawienie kontaktu."
        )
        firma.save(
            update_fields=[
                "widget_title",
                "widget_welcome_message",
                "gpt_prompt",
            ]
        )
        return firma

    def _wyczysc(self, firma):
        """Kasuje tylko zawartość TEJ firmy — nigdy cudzej."""
        Conversation.objects.filter(tenant=firma).delete()
        PromptLog.objects.filter(tenant=firma).delete()
        ContactRequest.objects.filter(tenant=firma).delete()
        Document.objects.filter(tenant=firma).delete()
        FAQ.objects.filter(tenant=firma).delete()

    def _konto(self, firma, email, haslo):
        uzytkownik = CustomUser.objects.filter(username=email).first()
        if uzytkownik is None:
            uzytkownik = CustomUser.objects.create_user(
                username=email,
                email=email,
                password=haslo,
                tenant=firma,
                role=UserRole.VIEWER,
            )
        else:
            uzytkownik.tenant = firma
            uzytkownik.role = UserRole.VIEWER
            uzytkownik.set_password(haslo)
            uzytkownik.save()
        return uzytkownik

    def _subskrypcja(self, firma):
        Subscription.objects.update_or_create(
            tenant=firma,
            defaults={
                "plan_type": "grow",
                "start_date": date.today() - timedelta(days=30),
                "end_date": date.today() + timedelta(days=335),
                "message_limit": 8000,
                "current_message_count": 512,
                "is_active": True,
            },
        )

    def _dokumenty(self, firma, losowy):
        for adres, nazwa, tresc in DOKUMENTY_DEMO:
            dokument = Document.objects.create(
                tenant=firma,
                # Nazwa czytelna, nie adres. `tekst_do_wektora` doklein ja do
                # kazdego fragmentu przed policzeniem wektora, wiec "Cennik
                # uslug serwisowych" daje wyszukiwaniu kontekst, ktorego
                # "https://rowerownia-demo.pl/cennik" nie niesie. Adres i tak
                # zostaje w source_url, ktory jest od tego.
                name=nazwa,
                content=tresc,
                # processed=False na czas zakladania. Dokument oznaczony jako
                # przetworzony, ktory nie ma jeszcze fragmentow, odpala sygnal
                # post_save i ten generuje WLASNY komplet fragmentow przez
                # OpenAI. Zasiew dokladal potem drugi komplet, wiec demo
                # konczylo z dwoma kopiami tej samej tresci: jedna z wektorami
                # prawdziwymi, druga z losowymi.
                #
                # Tak wlasnie wygladalo demo na produkcji. Przy okazji zasiew,
                # ktory z zalozenia "nie wola OpenAI", wolal je po cichu przy
                # kazdym uruchomieniu.
                processed=False,
                source="website",
                source_url=adres,
                znakow_na_stronie=len(tresc),
            )

            # Ten sam dzielnik, ktory tnie dokumenty klientow. Wlasny podzial
            # dalby demo fragmenty innego ksztaltu niz produkcja - a wtedy
            # demo przestaloby pokazywac, jak produkt naprawde dziala.
            for fragment in podziel_na_fragmenty(tresc):
                DocumentChunk.objects.create(
                    document=dokument,
                    content=fragment,
                    # Losowy wektor poprawnego wymiaru: zasiew ma dzialac bez
                    # klucza OpenAI. Sens przychodzi po `przelicz_fragmenty`,
                    # ktore policzy wektory z TEJ tresci - a nie, jak dotad,
                    # z wypelniacza.
                    embedding=[losowy.uniform(-1, 1) for _ in range(WYMIAR_WEKTORA)],
                )

            # Teraz mozna. Sygnal odpali sie ponownie, ale fragmenty juz sa,
            # wiec nie zleci ich generowania po raz drugi.
            dokument.processed = True
            dokument.save(update_fields=["processed"])

    def _faq(self, firma):
        FAQ.objects.bulk_create([FAQ(tenant=firma, question=p, answer=o) for p, o in FAQ_DEMO])

    def _ruch(self, firma, dni, losowy):
        """Rozmowy rozłożone w czasie, z przewagą dni roboczych."""
        teraz = timezone.now()
        rozmow = wiadomosci = 0

        for dzien in range(dni):
            data = teraz - timedelta(days=dzien)
            # W weekend ruch spada — inaczej wykres na pulpicie wygląda
            # jak wygenerowany, bo jest idealnie równy.
            ile = losowy.randint(0, 1) if data.weekday() >= 5 else losowy.randint(1, 4)

            for _ in range(ile):
                bez_pokrycia = losowy.random() < 0.22
                pytanie, zrodlo = (
                    (losowy.choice(PYTANIA_BEZ_POKRYCIA), "gpt")
                    if bez_pokrycia
                    else losowy.choice(PYTANIA_ZNANE)
                )
                odpowiedz = ODPOWIEDZ_BRAK if bez_pokrycia else self._odpowiedz(pytanie)

                rozmowa = Conversation.objects.create(
                    tenant=firma,
                    user_identifier=f"gosc-{losowy.randint(1000, 9999)}",
                    status="closed",
                    source="widget",
                )
                # auto_now_add nie da się ustawić przy tworzeniu — cofamy
                # datę osobnym update, inaczej cały ruch ma dzisiejszą datę
                # i wykres na pulpicie jest jednym słupkiem.
                chwila = data - timedelta(hours=losowy.randint(0, 9))
                Conversation.objects.filter(pk=rozmowa.pk).update(
                    started_at=chwila,
                    last_message_at=chwila,
                )

                for nadawca, tresc, zrodlo_wiad in (
                    ("user", pytanie, "manual"),
                    ("bot", odpowiedz, zrodlo),
                ):
                    wiadomosc = ChatMessage.objects.create(
                        conversation=rozmowa,
                        sender=nadawca,
                        message=tresc,
                        source=zrodlo_wiad,
                        token_count=len(tresc) // 4,
                    )
                    ChatMessage.objects.filter(pk=wiadomosc.pk).update(timestamp=chwila)
                    wiadomosci += 1

                dziennik = PromptLog.objects.create(
                    tenant=firma,
                    conversation=rozmowa,
                    model="gpt-4o-mini",
                    prompt=pytanie,
                    response=odpowiedz,
                    source=zrodlo,
                    tokens=(len(pytanie) + len(odpowiedz)) // 4,
                )
                PromptLog.objects.filter(pk=dziennik.pk).update(created_at=chwila)
                rozmow += 1

        return rozmow, wiadomosci

    def _odpowiedz(self, pytanie):
        for pyt, odp in FAQ_DEMO:
            wspolne = set(pytanie.lower().split()) & set(pyt.lower().split())
            if len(wspolne) >= 2:
                return odp
        return FAQ_DEMO[1][1]

    def _zapytania(self, firma, losowy):
        teraz = timezone.now()
        for numer, (imie, kontakt, tresc) in enumerate(KONTAKTY_DEMO):
            zapytanie = ContactRequest.objects.create(
                tenant=firma,
                name=imie,
                contact=kontakt,
                message=tresc,
                handled=numer >= 3,
            )
            ContactRequest.objects.filter(pk=zapytanie.pk).update(
                created_at=teraz - timedelta(days=losowy.randint(0, 20)),
            )
