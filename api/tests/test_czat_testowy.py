"""
Rozmowa właściciela z własnym botem, z panelu.

Bez niej po wgraniu wiedzy nie było jak sprawdzić, czy bot cokolwiek z niej
umie — jedyną drogą było wystawienie go na żywo i czekanie na prawdziwego
odwiedzającego.

Testujemy dwie rzeczy, na których stoi sens tej funkcji: że test nie kosztuje
klienta wiadomości z pakietu i że nie zanieczyszcza liczb. To drugie jest
ważniejsze, niż wygląda — właściciel testuje bota akurat tymi pytaniami,
o których wie, że są trudne. Gdyby szły do raportu luk, sam wypełniłby sobie
listę "czego szukają Twoi klienci" własnymi próbami i zepsuł jedyną liczbę
w tym produkcie mówiącą coś o rynku, a nie o nas.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, Subscription, Tenant
from chat.models import ChatMessage, Conversation, PromptLog
from chat.raport_luk import luki_w_wiedzy
from chat.zapytania import ZRODLO_TESTOWE, logi_klientow, rozmowy_klientow

URL = "/api/chat/test/"


class StrumienUdawany:
    def __init__(self, kawalki):
        self.kawalki = kawalki

    def __iter__(self):
        for kawalek in self.kawalki:
            yield type("Zdarzenie", (), {
                "usage": None,
                "choices": [type("Wybor", (), {
                    "delta": type("Delta", (), {"content": kawalek})()
                })()],
            })()


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Dwor Weselny", owner_email="w@firma.pl")
    Subscription.objects.create(
        tenant=tenant, plan_type="start", is_active=True,
        message_limit=2000, current_message_count=0,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


@pytest.fixture
def panel(firma):
    uzytkownik = CustomUser.objects.create_user(
        username="wl", email="wl@firma.pl", password="x",
        tenant=firma, role="owner",
    )
    klient = APIClient()
    klient.force_authenticate(user=uzytkownik)
    klient.credentials(HTTP_X_API_KEY=str(firma.api_key))
    return klient


def rozmawiaj(klient, tresc, odpowiedz="Sala miesci 120 osob."):
    with patch("api.utils.chat_engine.get_client") as openai, \
         patch("api.utils.chat_engine.build_chat_messages", return_value=([], [], [])):
        openai.return_value.chat.completions.create.return_value = StrumienUdawany([odpowiedz])
        wynik = klient.post(URL, {"message": tresc}, format="json")
        # Strumień jest leniwy — bez skonsumowania nic się nie zapisze
        tresc_odpowiedzi = b"".join(wynik.streaming_content).decode()
    return wynik, tresc_odpowiedzi


@pytest.mark.django_db
class TestDzialania:
    def test_bot_odpowiada_strumieniem(self, panel):
        wynik, tresc = rozmawiaj(panel, "Ile osob miesci sala?")

        assert wynik.status_code == 200
        assert "Sala miesci 120 osob." in tresc

    def test_rozmowa_wraca_po_odswiezeniu_panelu(self, panel):
        rozmawiaj(panel, "Ile osob miesci sala?")

        odp = panel.get(URL)

        assert odp.status_code == 200
        wiadomosci = odp.json()["messages"]
        assert [w["sender"] for w in wiadomosci] == ["user", "bot"]
        assert wiadomosci[0]["text"] == "Ile osob miesci sala?"

    def test_da_sie_wyczyscic_i_zaczac_od_nowa(self, panel):
        """Po uzupełnieniu wiedzy testuje się od zera — inaczej stara historia
        wchodzi do promptu i bot odpowiada na poprzednie pytanie."""
        rozmawiaj(panel, "Ile osob miesci sala?")

        assert panel.delete(URL).status_code == 200
        assert panel.get(URL).json()["messages"] == []

    def test_pusta_wiadomosc_to_blad_zadania_nie_brak_uprawnien(self, panel):
        assert panel.post(URL, {"message": "   "}, format="json").status_code == 400

    def test_bez_logowania_ani_slowa(self, firma):
        anonim = APIClient()
        anonim.credentials(HTTP_X_API_KEY=str(firma.api_key))

        assert anonim.post(URL, {"message": "czesc"}, format="json").status_code in (401, 403)


@pytest.mark.django_db
class TestNieKosztuje:
    def test_limit_wiadomosci_nie_rusza_sie(self, panel, firma):
        """Sprawdzanie własnego bota nie może zjadać pakietu, za który klient
        płaci — inaczej testowanie kosztuje i nikt nie testuje."""
        przed = firma.subscription.current_message_count

        rozmawiaj(panel, "Ile osob miesci sala?")

        firma.subscription.refresh_from_db()
        assert firma.subscription.current_message_count == przed


@pytest.mark.django_db
class TestNieZanieczyszczaLiczb:
    def test_nie_wchodzi_do_raportu_luk(self, panel, firma):
        """Najważniejszy z tych testów. Właściciel testuje bota akurat
        trudnymi pytaniami — gdyby szły do raportu, sam wypełniłby sobie
        listę "czego szukają Twoi klienci" własnymi próbami."""
        with patch("api.utils.chat_engine.determine_source", return_value="gpt"):
            rozmawiaj(panel, "Czy organizujecie chrzciny?")

        assert PromptLog.objects.filter(tenant=firma, source="gpt").exists()
        assert luki_w_wiedzy(firma) == []

    def test_nie_liczy_sie_do_statystyk_pulpitu(self, panel, firma):
        rozmawiaj(panel, "Ile osob miesci sala?")

        odp = panel.get("/api/analytics/")

        assert odp.json()["conversations"]["total"] == 0
        assert odp.json()["questions"]["total"] == 0

    def test_nie_pokazuje_sie_w_historii_rozmow(self, panel):
        rozmawiaj(panel, "Ile osob miesci sala?")

        odp = panel.get("/api/chat/logs/")

        # Bez PAGE_SIZE w ustawieniach DRF oddaje zwykłą listę, nie kopertę
        # ze stronicowaniem — test przyjmuje obie postacie, bo pilnuje treści,
        # a nie tego, czy kiedyś włączymy stronicowanie.
        dane = odp.json()
        assert (dane["results"] if isinstance(dane, dict) else dane) == []

    def test_rozmowa_ma_zrodlo_testowe(self, panel, firma):
        rozmawiaj(panel, "Ile osob miesci sala?")

        assert Conversation.objects.filter(tenant=firma).count() == 1
        assert Conversation.objects.get(tenant=firma).source == ZRODLO_TESTOWE
        assert rozmowy_klientow(firma).count() == 0

    def test_prawdziwy_ruch_nadal_sie_liczy(self, panel, firma):
        """Filtr ma odcinać testy, nie wszystko."""
        prawdziwa = Conversation.objects.create(
            tenant=firma, user_identifier="gosc", source="widget"
        )
        ChatMessage.objects.create(conversation=prawdziwa, sender="user", message="Ile kosztuje?")
        PromptLog.objects.create(
            tenant=firma, conversation=prawdziwa, model="m",
            prompt="Ile kosztuje?", source="gpt",
        )
        rozmawiaj(panel, "moje testowe pytanie")

        assert rozmowy_klientow(firma).count() == 1
        assert [p["pytanie"] for p in luki_w_wiedzy(firma)] == ["Ile kosztuje?"]

    def test_wpis_po_skasowanej_rozmowie_nie_znika_z_liczb(self, firma):
        """Retencja kasuje rozmowy, zostawiając PromptLog z pustym powiązaniem
        (SET_NULL). Takie wpisy pochodzą sprzed usunięcia, nie z testu —
        `exclude()` po pustym powiązaniu musi je zachować."""
        PromptLog.objects.create(
            tenant=firma, conversation=None, model="m",
            prompt="Pytanie po retencji", source="gpt",
        )

        assert logi_klientow(firma).count() == 1
        assert [p["pytanie"] for p in luki_w_wiedzy(firma)] == ["Pytanie po retencji"]


@pytest.mark.django_db
class TestIzolacjiMiedzyOsobami:
    def test_kazdy_pracownik_ma_wlasna_rozmowe(self, firma, panel):
        """Wspólna rozmowa oznaczałaby mieszanie historii — a historia wchodzi
        do promptu, więc bot odpowiadałby jednej osobie na pytanie drugiej."""
        rozmawiaj(panel, "pytanie wlasciciela")

        drugi = CustomUser.objects.create_user(
            username="prac", email="prac@firma.pl", password="x",
            tenant=firma, role="employee",
        )
        klient2 = APIClient()
        klient2.force_authenticate(user=drugi)
        klient2.credentials(HTTP_X_API_KEY=str(firma.api_key))

        assert klient2.get(URL).json()["messages"] == []
        assert Conversation.objects.filter(tenant=firma, source=ZRODLO_TESTOWE).count() == 2
