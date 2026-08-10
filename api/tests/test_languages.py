"""
Język odpowiedzi bota.

Prompt miał zaszyte "odpowiadaj po polsku", więc anglojęzyczny odwiedzający
dostawał polską odpowiedź na angielskie pytanie. Badanie rynku stawia PL/EN
jako wymóg podstawowy.

Język rozpoznajemy w kodzie (api.utils.language), a model dostaje instrukcję
wskazującą jeden, gotowy język. Zakres jest zamknięty listą klienta: odpowiedź
w języku, którego firma nie obsłuży po eskalacji do człowieka, byłaby obietnicą
bez pokrycia.
"""
import pytest
from rest_framework.test import APIClient

from accounts.models import Tenant
from api.utils.chat_engine import build_system_prompt, language_instruction
from api.utils.language import jezyk_odpowiedzi, wykryj_jezyk


class TestParsowanieJezykow:
    def test_lista_kodow_po_przecinku(self):
        assert Tenant(widget_languages="pl,en").languages() == ["pl", "en"]

    def test_wielkosc_liter_i_spacje_bez_znaczenia(self):
        assert Tenant(widget_languages=" PL , En ").languages() == ["pl", "en"]

    def test_nieznane_kody_odpadaja(self):
        assert Tenant(widget_languages="pl,klingoński,en").languages() == ["pl", "en"]

    @pytest.mark.parametrize("wartosc", ["", "   ", "xx,yy", None])
    def test_brak_poprawnego_kodu_daje_polski(self, wartosc):
        """
        Literówka w konfiguracji nie może zostawić bota bez języka — wtedy
        model wybierałby go sobie sam przy każdej odpowiedzi.
        """
        assert Tenant(widget_languages=wartosc).languages() == ["pl"]

    def test_pierwszy_jest_domyslny(self):
        assert Tenant(widget_languages="en,pl").languages()[0] == "en"


class TestWykrywaniaJezyka:
    """
    Wykrywanie siedzi w kodzie, nie w promptcie. Wersje opisujące modelowi listę
    dozwolonych języków wypadały na żywym modelu niestabilnie — albo lustrzanie
    dopasowywał język pytania i ignorował listę klienta, albo zwijał wszystko
    do domyślnego i ignorował zezwolenie.
    """

    @pytest.mark.parametrize("tekst,kod", [
        ("Jakie macie godziny otwarcia?", "pl"),
        ("Ile kosztuje przegląd roweru?", "pl"),
        ("What are your opening hours?", "en"),
        ("How much does delivery cost?", "en"),
        ("Wie sind Ihre Öffnungszeiten?", "de"),
        ("Guten Tag, ich möchte eine Bestellung", "de"),
        ("Які у вас години роботи?", "uk"),
    ])
    def test_rozpoznaje_obslugiwane_jezyki(self, tekst, kod):
        assert wykryj_jezyk(tekst) == kod

    @pytest.mark.parametrize("tekst", [
        "¿Cuál es su horario de apertura?",   # hiszpański
        "Quels sont vos horaires ?",          # francuski
        "Quanto costa la consegna?",          # włoski
        "ok", "???", "", "   ",
    ])
    def test_nierozpoznane_zwraca_none(self, tekst):
        """
        None to pełnoprawny wynik — takie pytanie ma trafić na język domyślny
        firmy, a nie na siłę do najbliższego z listy.
        """
        assert wykryj_jezyk(tekst) is None


class TestWyboruJezykaOdpowiedzi:
    def test_jezyk_pytania_gdy_dozwolony(self):
        assert jezyk_odpowiedzi("What are your opening hours?", ["pl", "en"]) == "en"

    def test_jezyk_pytania_gdy_niedozwolony_wraca_do_domyslnego(self):
        """Sedno ograniczenia: klient obsługuje PL i EN, pytanie przyszło po niemiecku."""
        assert jezyk_odpowiedzi("Wie sind Ihre Öffnungszeiten?", ["pl", "en"]) == "pl"

    def test_jezyk_spoza_calej_obslugiwanej_czworki(self):
        assert jezyk_odpowiedzi("¿Cuál es su horario?", ["pl", "en", "de"]) == "pl"

    def test_domyslnym_jest_pierwszy_z_listy(self):
        assert jezyk_odpowiedzi("¿Cuál es su horario?", ["en", "pl"]) == "en"


class TestTrybuJezykowego:
    """
    Dwa tryby zamiast jednej listy, w której domyślny język był po cichu
    pierwszym zaznaczonym — a kolejność zaznaczania zależała od tego, w co
    klient kliknął najpierw, więc nie miał na nią wpływu ani jej nie widział.
    """

    def test_tryb_staly_ignoruje_jezyk_pytania(self):
        tenant = Tenant(
            widget_language_mode="fixed",
            widget_default_language="pl",
            widget_languages="pl,en",
        )

        instrukcja = language_instruction(tenant, "What are your opening hours?")

        assert "wyłącznie po polsku" in instrukcja

    def test_tryb_auto_dopasowuje_sie_do_pytania(self):
        tenant = Tenant(
            widget_language_mode="auto",
            widget_default_language="pl",
            widget_languages="pl,en",
        )

        instrukcja = language_instruction(tenant, "What are your opening hours?")

        assert "wyłącznie po angielsku" in instrukcja

    def test_domyslny_jest_niezalezny_od_kolejnosci_listy(self):
        """Sedno zmiany: lista mówi 'en,pl', ale domyślnym jest to, co wybrał klient."""
        tenant = Tenant(
            widget_language_mode="auto",
            widget_default_language="pl",
            widget_languages="en,pl",
        )

        assert tenant.default_language() == "pl"
        assert "wyłącznie po polsku" in language_instruction(tenant, "¿Cuál es su horario?")

    @pytest.mark.parametrize("wartosc", ["", "xx", None])
    def test_uszkodzony_domyslny_wraca_do_polskiego(self, wartosc):
        assert Tenant(widget_default_language=wartosc).default_language() == "pl"

    @pytest.mark.parametrize("kod,forma", [
        ("ru", "po rosyjsku"), ("cs", "po czesku"),
        ("uk", "po ukraińsku"), ("de", "po niemiecku"),
    ])
    def test_nowe_jezyki_maja_poprawna_forme_w_promptcie(self, kod, forma):
        tenant = Tenant(widget_language_mode="fixed", widget_default_language=kod)

        assert forma in language_instruction(tenant, "cokolwiek")


class TestInstrukcjaWPromptcie:
    def test_instrukcja_wskazuje_zawsze_jeden_jezyk(self):
        instrukcja = language_instruction(
            Tenant(widget_languages="pl,en"), "What are your opening hours?"
        )

        assert instrukcja == "Odpowiadaj wyłącznie po angielsku, niezależnie od języka pytania."

    def test_pytanie_w_niedozwolonym_jezyku_daje_domyslny(self):
        instrukcja = language_instruction(
            Tenant(widget_languages="pl,en"), "Wie sind Ihre Öffnungszeiten?"
        )

        assert "wyłącznie po polsku" in instrukcja

    def test_bez_wiadomosci_uzywamy_domyslnego(self):
        assert "wyłącznie po polsku" in language_instruction(Tenant(widget_languages="pl,en"))

    def test_niedozwolony_jezyk_nie_trafia_do_promptu(self):
        """Klient wybrał PL i EN — bot nie ma prawa odpowiedzieć po niemiecku."""
        instrukcja = language_instruction(
            Tenant(widget_languages="pl,en"), "Wie sind Ihre Öffnungszeiten?"
        )

        assert "niemiecku" not in instrukcja
        assert "ukraińsku" not in instrukcja

    @pytest.mark.django_db
    def test_instrukcja_jest_czescia_promptu_systemowego(self, tenant):
        """
        Strażnik: przy jednej z wcześniejszych zmian instrukcja wypadła z promptu
        i nikt tego nie zauważył, bo pozostałe testy sprawdzały wyłącznie treść
        samego zdania, nigdy jego obecność w gotowym promptcie.
        """
        tenant.widget_languages = "pl,en"
        tenant.save()

        prompt = build_system_prompt(
            tenant, chunks=[], faqs=[], message="What are your opening hours?"
        )

        assert "Odpowiadaj wyłącznie po angielsku" in prompt
        # Stara, zaszyta na sztywno instrukcja nie może zostać w prompcie
        assert "Odpowiadaj po polsku," not in prompt

    @pytest.mark.django_db
    def test_jezyk_zalezy_od_wiadomosci_a_nie_tylko_od_konfiguracji(self, tenant):
        """
        Drugi strażnik tego samego błędu: gdyby instrukcja wypadła z promptu,
        oba warianty wyszłyby identyczne mimo różnych pytań.
        """
        tenant.widget_languages = "pl,en"
        tenant.save()

        po_polsku = build_system_prompt(tenant, [], [], message="Jakie macie godziny?")
        po_angielsku = build_system_prompt(tenant, [], [], message="What are your hours?")

        assert po_polsku != po_angielsku


@pytest.mark.django_db
class TestUstawienieWPanelu:
    def test_widget_dostaje_liste_jezykow(self, tenant):
        tenant.widget_languages = "pl,en,uk"
        tenant.save()

        dane = APIClient().get(
            "/api/widget-settings/", HTTP_X_API_KEY=str(tenant.api_key)
        ).json()

        assert dane["widget_languages"] == ["pl", "en", "uk"]

    def test_wlasciciel_zmienia_jezyki(self, user, tenant):
        user.tenant = tenant
        user.role = "owner"
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_API_KEY=str(tenant.api_key))

        response = client.patch(
            "/api/widget-settings/mine/", {"widget_languages": "pl,de"}, format="json"
        )

        assert response.status_code == 200
        tenant.refresh_from_db()
        assert tenant.languages() == ["pl", "de"]
