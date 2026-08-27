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
    ChatMessage,
    ContactRequest,
    Conversation,
    FAQ,
    PromptLog,
)
from documents.models import Document, DocumentChunk

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

DOKUMENTY_DEMO = [
    ("https://rowerownia-demo.pl/cennik", "Cennik usług serwisowych", 4820),
    ("https://rowerownia-demo.pl/serwis", "Zakres serwisu i naprawy", 6310),
    ("https://rowerownia-demo.pl/kontakt", "Kontakt i godziny otwarcia", 1240),
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
        self.stdout.write(f"  Rola         : viewer (tylko odczyt)")
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
        for adres, nazwa, znakow in DOKUMENTY_DEMO:
            dokument = Document.objects.create(
                tenant=firma,
                name=adres,
                content="x" * int(znakow * 0.72),
                processed=True,
                source="website",
                source_url=adres,
                znakow_na_stronie=znakow,
            )
            # Losowy wektor poprawnego wymiaru: wyszukiwanie ma działać
            # mechanicznie bez klucza OpenAI. Sens przychodzi dopiero po
            # przeliczeniu fragmentów prawdziwym modelem.
            for numer in range(max(3, znakow // 1200)):
                DocumentChunk.objects.create(
                    document=dokument,
                    content=f"{nazwa} — fragment {numer + 1}",
                    embedding=[losowy.uniform(-1, 1) for _ in range(WYMIAR_WEKTORA)],
                )

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
