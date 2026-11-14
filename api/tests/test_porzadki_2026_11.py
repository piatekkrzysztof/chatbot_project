"""
Porządki po przeglądzie końcowym 11.11.2026 - lista „Niskie i porządki"
z docs/przeglad-koncowy-2026-11.md, partie pierwsza (2.32.33) i druga (2.32.34).

Każda klasa to jedna pozycja listy. Opis przy klasie mówi, co było przedtem.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant
from documents.models import Document


@pytest.fixture(autouse=True)
def czysta_pamiec():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def firma(db):
    return Tenant.objects.create(name="Porządki", owner_email="szef@porzadki.example")


def klient_panelu(tenant, **pola):
    osoba = CustomUser.objects.create_user(
        username=pola.pop("username", "szef"),
        email=pola.pop("email", "szef@porzadki.example"),
        password="haslo-2026-x",
        tenant=tenant,
        role="owner",
        **pola,
    )
    klient = APIClient()
    klient.force_authenticate(user=osoba)
    klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return klient


@pytest.mark.django_db
class TestZaDlugiAdresPodstrony:
    """
    Adres podstrony dłuższy niż kolumna (200 znaków) kończył import surowym
    błędem bazy, który trafiał do komunikatu dla klienta.
    """

    DLUGI = "https://firma.example/oferta?" + "filtr=wartosc&" * 20

    def test_import_odmawia_zwyklym_zdaniem_przed_pobraniem(self, firma):
        from documents import website_import

        assert len(self.DLUGI) > 200
        with patch.object(website_import, "fetch_page") as pobranie:
            with pytest.raises(ValueError, match="za długi"):
                website_import.import_website_as_document(firma, self.DLUGI, name="x")

        pobranie.assert_not_called()
        assert not Document.objects.exists()

    def test_wyszukiwanie_linkow_pomija_adres_ktorego_nie_da_sie_zapisac(self):
        from documents import website_import
        from documents.safe_http import Page

        glowna = f'<a href="{self.DLUGI}">Filtry</a><a href="/kontakt">Kontakt</a>'.encode()

        def pobierz(url):
            tresc = glowna if url == "https://firma.example/" else b"<p>Kontakt</p>"
            return Page(url, tresc, "text/html")

        with patch.object(website_import, "fetch_page", side_effect=pobierz):
            znalezione = website_import.discover_links_recursively("https://firma.example/")

        assert "https://firma.example/kontakt" in znalezione
        assert not any(len(adres) > 200 for adres in znalezione)

    def test_adres_na_granicy_dalej_sie_importuje(self, firma):
        """Straż: 200 znaków to jeszcze poprawny adres."""
        from documents import website_import
        from documents.utils.tresc_strony import TrescStrony

        adres = "https://firma.example/" + "a" * (200 - len("https://firma.example/"))
        tresc = "Cennik salonu. " * 20
        with patch.object(
            website_import, "fetch_text_from_url", return_value=TrescStrony(tresc, len(tresc))
        ):
            dokument = website_import.import_website_as_document(firma, adres, name="x")

        assert dokument.source_url == adres


@pytest.mark.django_db
class TestDiagnostykaBezNazwHostow:
    """
    Ekran „Stan systemu" oddawał każdej osobie z każdej firmy nazwy hostów
    workerów i treść błędu połączenia z brokerem.
    """

    BROKER = {
        "broker_osiagalny": True,
        "odpowiedzialo_workerow": 2,
        "nazwy": ["celery@srv-abc123-worker", "celery@srv-def456-worker"],
    }
    AWARIA = {
        "broker_osiagalny": False,
        "odpowiedzialo_workerow": 0,
        "nazwy": [],
        "blad": "ConnectionError: Error 111 connecting to red-abc123:6379.",
    }

    def odpytaj(self, klient, broker):
        from api.views import diagnostyka_zadan

        with patch.object(diagnostyka_zadan, "_stan_brokera", return_value=dict(broker)):
            odpowiedz = klient.get("/api/diagnostyka/zadania/")
        assert odpowiedz.status_code == 200
        return odpowiedz

    def test_klient_widzi_liczbe_workerow_bez_nazw(self, firma):
        odpowiedz = self.odpytaj(klient_panelu(firma), self.BROKER)

        assert "srv-abc123" not in odpowiedz.content.decode()
        assert '"odpowiedzialo_workerow":2' in odpowiedz.content.decode().replace(" ", "")

    def test_klient_nie_widzi_adresu_brokera_w_bledzie(self, firma):
        odpowiedz = self.odpytaj(klient_panelu(firma), self.AWARIA)

        tresc = odpowiedz.content.decode()
        assert "red-abc123" not in tresc
        assert "Kolejka zadań nie odpowiada" in tresc

    def test_obsluga_dalej_widzi_szczegoly(self, firma):
        odpowiedz = self.odpytaj(klient_panelu(firma, is_staff=True), self.BROKER)

        assert "srv-abc123" in odpowiedz.content.decode()


@pytest.mark.django_db
class TestDomyslneUprawnieniaApi:
    """
    Bez `DEFAULT_PERMISSION_CLASSES` domyślne DRF to AllowAny: widok bez
    własnych uprawnień byłby publiczny. Przeglądalne API działało w produkcji.
    """

    def test_widok_bez_wlasnych_uprawnien_wymaga_logowania(self):
        from rest_framework.response import Response
        from rest_framework.test import APIRequestFactory
        from rest_framework.views import APIView

        class NowyWidok(APIView):
            authentication_classes = ()

            def get(self, request):
                return Response({"ok": True})

        odpowiedz = NowyWidok.as_view()(APIRequestFactory().get("/x/"))

        assert odpowiedz.status_code in (401, 403)

    def test_api_nie_oddaje_strony_html(self, firma):
        odpowiedz = klient_panelu(firma).get("/api/faq/", HTTP_ACCEPT="text/html")

        assert "text/html" not in odpowiedz.get("Content-Type", "")

    def test_publiczne_adresy_dalej_dzialaja_bez_logowania(self, firma):
        """Straż: widget i logowanie mówią wprost, że są publiczne."""
        widget = APIClient().get("/api/widget-settings/", HTTP_X_API_KEY=str(firma.api_key))
        logowanie = APIClient(HTTP_ORIGIN="https://panel.example.test").post(
            "/api/accounts/login/", {"username": "nikt", "password": "zle"}, format="json"
        )

        assert widget.status_code == 200
        assert logowanie.status_code == 401
        assert "Nie podano" not in logowanie.content.decode()


@pytest.mark.django_db
class TestLimitDoreczenWektorow:
    """
    `acks_late` z `reject_on_worker_lost` oddaje zadanie do kolejki, gdy worker
    zginie. Dokument, który sam zabija proces, wracał więc bez końca
    i blokował jedynego workera.
    """

    def dokument(self, firma):
        return Document.objects.create(tenant=firma, name="duzy.pdf", content="Treść. " * 50)

    def test_po_limicie_doreczen_zadanie_odpuszcza_i_zostawia_slad(self, firma):
        from documents import tasks

        dokument = self.dokument(firma)
        przeliczenia = []

        def worker_ginie(doc):
            # Utrata workera: zadanie nie dochodzi ani do końca, ani do except.
            przeliczenia.append(doc.pk)
            raise SystemExit("worker lost")

        with patch.object(tasks, "_generate_embeddings", side_effect=worker_ginie):
            for _ in range(tasks.MAKS_DORECZEN):
                with pytest.raises(SystemExit):
                    tasks.generate_embeddings_for_document(dokument.pk)
            tasks.generate_embeddings_for_document(dokument.pk)

        assert len(przeliczenia) == tasks.MAKS_DORECZEN
        dokument.refresh_from_db()
        assert "przerwało pracę serwera" in dokument.processing_error

    def test_udane_przeliczenia_nie_zblizaja_do_limitu(self, firma):
        """Straż: dokument odświeżany wiele razy dziennie przelicza się zawsze."""
        from documents import tasks

        dokument = self.dokument(firma)
        with patch.object(tasks, "_generate_embeddings") as przeliczenie:
            for _ in range(tasks.MAKS_DORECZEN + 3):
                tasks.generate_embeddings_for_document(dokument.pk)

        assert przeliczenie.call_count == tasks.MAKS_DORECZEN + 3
        dokument.refresh_from_db()
        assert dokument.processing_error == ""

    def test_zwykly_blad_nie_liczy_sie_jak_utrata_workera(self, firma):
        from documents import tasks

        dokument = self.dokument(firma)
        with patch.object(tasks, "_generate_embeddings", side_effect=RuntimeError("api")) as proba:
            for _ in range(tasks.MAKS_DORECZEN + 2):
                with pytest.raises(RuntimeError):
                    tasks.generate_embeddings_for_document(dokument.pk)

        assert proba.call_count == tasks.MAKS_DORECZEN + 2


@pytest.mark.django_db
class TestHealthNieOtwieraBrokeraZaKazdymRazem:
    """
    Publiczny `/health/` otwierał połączenie z Redisem przy każdym żądaniu.
    """

    def test_kolejne_zadania_korzystaja_z_jednego_sprawdzenia(self, client):
        with patch("chatbot_project.zdrowie._broker_odpowiada", return_value=True) as broker:
            for _ in range(5):
                assert client.get("/health/").status_code == 200

        assert broker.call_count == 1

    def test_po_uplywie_pamieci_sprawdza_od_nowa(self, client):
        from chatbot_project import zdrowie

        with patch("chatbot_project.zdrowie._broker_odpowiada", return_value=True) as broker:
            client.get("/health/")
            czas, wynik = zdrowie._broker_ostatnio
            zdrowie._broker_ostatnio = (czas - zdrowie.BROKER_PAMIEC_S - 1, wynik)
            client.get("/health/")

        assert broker.call_count == 2


# --- partia druga (2.32.34) ----------------------------------------------------


@pytest.mark.django_db
class TestLimitLogowaniaNaKonto:
    """
    Limit prób na konto liczył wpisany tekst. Nazwa użytkownika i adres e-mail
    tej samej osoby miały osobne liczniki - dwa razy więcej prób zgadywania.
    """

    def klucz(self, nazwa):
        from rest_framework.test import APIRequestFactory
        from rest_framework.views import APIView

        from api.throttles import LimitLogowaniaKonto

        zadanie = APIView().initialize_request(
            APIRequestFactory().post("/x/", {"username": nazwa, "password": "x"}, format="json")
        )
        return LimitLogowaniaKonto().get_cache_key(zadanie, None)

    def test_nazwa_i_adres_tego_samego_konta_maja_wspolny_licznik(self, firma):
        CustomUser.objects.create_user(
            username="jan.kowalski", email="jan@firma.example", password="x", tenant=firma
        )

        assert self.klucz("jan.kowalski") == self.klucz("JAN@firma.example")

    def test_rozne_konta_maja_rozne_liczniki(self, firma):
        CustomUser.objects.create_user(
            username="jan", email="jan@firma.example", password="x", tenant=firma
        )
        CustomUser.objects.create_user(
            username="ewa", email="ewa@firma.example", password="x", tenant=firma
        )

        assert self.klucz("jan") != self.klucz("ewa")

    def test_nieznana_nazwa_dalej_ma_licznik_i_nie_zdradza_konta(self, firma):
        """Straż: tekst bez konta jest ograniczany po samym tekście."""
        klucz = self.klucz("nikt@nigdzie.example")

        assert klucz
        assert "nikt" not in klucz
        assert klucz == self.klucz("NIKT@nigdzie.example")


@pytest.mark.django_db
class TestAlarmStripePoPowtorzonymBledzie:
    """
    Pojedynczy błąd sieci przy rozmowie z API Stripe od razu oznaczał firmę
    jako wymagającą reakcji i wysyłał alarm do operatora.
    """

    def firma_z_subskrypcja(self):
        from accounts.models import Subscription

        tenant = Tenant.objects.create(name="Kontrola", owner_email="a@example.test")
        Subscription.objects.create(
            tenant=tenant,
            plan_type="pro",
            stripe_subscription_id=f"sub_{tenant.pk}",
            stripe_status="active",
            is_active=True,
            start_date="2026-01-01",
            end_date="2027-01-01",
        )
        return tenant

    def uzgodnij(self, blad):
        from accounts.tasks_stripe import uzgodnij_platnosci

        with patch("stripe.Subscription.retrieve", side_effect=blad):
            uzgodnij_platnosci()

    def test_pierwszy_blad_sieci_nie_alarmuje_i_jest_ponawiany(self, settings, mailoutbox):
        import stripe

        from accounts.stripe_sync import KontrolaStripe

        settings.EMAIL_ALERTOW = "operator@example.test"
        tenant = self.firma_z_subskrypcja()

        self.uzgodnij(stripe.error.APIConnectionError("sieć"))

        kontrola = KontrolaStripe.objects.get(tenant=tenant)
        assert kontrola.blad == ""
        # Znacznik próby cofnięty: następny przebieg bierze firmę od razu.
        assert kontrola.probowano_at is None
        assert mailoutbox == []

    def test_drugi_blad_sieci_z_rzedu_alarmuje(self, settings, mailoutbox):
        import stripe

        from accounts.stripe_sync import KontrolaStripe

        settings.EMAIL_ALERTOW = "operator@example.test"
        tenant = self.firma_z_subskrypcja()

        self.uzgodnij(stripe.error.APIConnectionError("sieć"))
        self.uzgodnij(stripe.error.APIConnectionError("sieć"))

        assert KontrolaStripe.objects.get(tenant=tenant).blad == "wymaga_uzgodnienia"
        assert len(mailoutbox) == 1

    def test_blad_ktory_nie_jest_chwilowy_alarmuje_od_razu(self, settings, mailoutbox):
        """Straż: odrzucone żądanie to dalej sprawa dla operatora."""
        import stripe

        from accounts.stripe_sync import KontrolaStripe

        settings.EMAIL_ALERTOW = "operator@example.test"
        tenant = self.firma_z_subskrypcja()

        self.uzgodnij(stripe.error.AuthenticationError("zły klucz"))

        assert KontrolaStripe.objects.get(tenant=tenant).blad == "wymaga_uzgodnienia"
        assert len(mailoutbox) == 1


@pytest.mark.django_db
class TestAwariaModeluWCzacie:
    """
    Awaria modelu przy trafionych fragmentach zapisywała źródło „document":
    wymiana liczyła się jako odpowiedź z wiedzy firmy, choć odwiedzający dostał
    komunikat o błędzie. Strumień urwany w połowie kończył się zwykłym `done`.
    """

    def test_awaria_modelu_bije_trafione_fragmenty(self):
        from api.utils.pokrycie import determine_source
        from chat.models import ZRODLO_BRAK_WIEDZY, ZRODLO_DOKUMENT

        fragmenty = [object()]

        assert determine_source(fragmenty, [], "Cennik?") == ZRODLO_DOKUMENT
        assert determine_source(fragmenty, [], "Cennik?", awaria_modelu=True) == ZRODLO_BRAK_WIEDZY

    def rozmowa(self, firma):
        from chat.models import Conversation

        return Conversation.objects.create(tenant=firma)

    def zlozone(self):
        wiadomosci = [{"role": "system", "content": "x"}, {"role": "user", "content": "Cennik?"}]
        return patch(
            "api.utils.chat_engine.build_chat_messages",
            return_value=(wiadomosci, [object()], [], False),
        )

    def test_odpowiedz_bez_strumienia_po_awarii_nie_jest_z_dokumentu(self, firma):
        from api.utils.chat_engine import FALLBACK_MESSAGE, process_chat_message
        from chat.models import ZRODLO_BRAK_WIEDZY

        with (
            self.zlozone(),
            patch("api.utils.chat_engine.get_openai_response", side_effect=RuntimeError("api")),
        ):
            wynik = process_chat_message(firma, self.rozmowa(firma), "Cennik?")

        assert wynik["response"] == FALLBACK_MESSAGE
        assert wynik["source"] == ZRODLO_BRAK_WIEDZY
        assert wynik["sources"] == []

    def strumien(self, firma, zdarzenia):
        import json

        from api.utils.chat_engine import stream_chat_message

        dostawca = MagicMock()
        dostawca.__iter__.return_value = zdarzenia
        with (
            self.zlozone(),
            patch("api.utils.chat_engine.get_client") as klient,
        ):
            klient.return_value.chat.completions.create.return_value = dostawca
            surowe = "".join(stream_chat_message(firma, self.rozmowa(firma), "Cennik?"))
        return [json.loads(wiersz[len("data: ") :]) for wiersz in surowe.split("\n\n") if wiersz]

    @staticmethod
    def kawalek(tekst):
        return Mock(usage=None, choices=[Mock(delta=Mock(content=tekst))])

    def test_strumien_urwany_w_polowie_jest_oznaczony(self, firma):
        def zdarzenia():
            yield self.kawalek("Strzyżenie kosztuje ")
            raise RuntimeError("połączenie zerwane")

        with patch("api.utils.chat_engine.zrodla_do_pokazania", return_value=[]):
            wynik = self.strumien(firma, zdarzenia())

        koniec = wynik[-1]
        assert koniec["type"] == "done"
        assert koniec["przerwana"] is True

    def test_strumien_bez_zadnego_slowa_nie_jest_z_dokumentu(self, firma):
        from chat.models import ZRODLO_BRAK_WIEDZY

        def zdarzenia():
            raise RuntimeError("model nie odpowiada")
            yield  # pragma: no cover

        wynik = self.strumien(firma, zdarzenia())

        assert wynik[-1]["source"] == ZRODLO_BRAK_WIEDZY

    def test_pelna_odpowiedz_nie_ma_znacznika_przerwania(self, firma):
        """Straż: zwykła odpowiedź kończy się tak jak dotąd."""
        from chat.models import ZRODLO_DOKUMENT

        with patch("api.utils.chat_engine.zrodla_do_pokazania", return_value=[]):
            wynik = self.strumien(firma, iter([self.kawalek("Strzyżenie kosztuje 90 zł.")]))

        assert "przerwana" not in wynik[-1]
        assert wynik[-1]["source"] == ZRODLO_DOKUMENT
