"""
Sprawdzenie stanu usługi.

Kategoria ryzyka: PRZYRZĄD, KTÓRY KŁAMIE. Poprzednia wersja tej funkcji
zwracała `{"status": "ok"}` bezwarunkowo - przy leżącej bazie, w środku
każdej możliwej awarii, zawsze zielono. Render decyduje na tej podstawie,
czy usługa żyje, a monitoring zewnętrzny, czy budzić człowieka.

Dlatego test „zdrowa usługa zwraca 200" jest tu najmniej wart: przechodziłby
także dla wersji, która nie sprawdza niczego. Wartość mają wyłącznie te,
które psują zależność i sprawdzają, że odpowiedź się zmienia.
"""

from unittest.mock import patch

import pytest


@pytest.mark.django_db
class TestZdrowejUslugi:
    def test_wszystko_dziala_to_200(self, client):
        with patch("chatbot_project.zdrowie._broker_odpowiada", return_value=True):
            odpowiedz = client.get("/health/")

        assert odpowiedz.status_code == 200
        dane = odpowiedz.json()
        assert dane["stan"] == "ok"
        assert dane["baza"] is True

    def test_stare_pole_status_zostaje(self, client):
        # Zewnetrzne czujki moga byc skonfigurowane na dokladnie te pare
        # klucz-wartosc. Zmiana nazwy zgasilaby je po cichu.
        with patch("chatbot_project.zdrowie._broker_odpowiada", return_value=True):
            assert client.get("/health/").json()["status"] == "ok"


@pytest.mark.django_db
class TestAwarii:
    def test_lezaca_baza_to_503(self, client):
        """
        Najważniejszy test w tym pliku.

        Bez bazy nie dziala nic - ani panel, ani widget. Poprzednia wersja
        odpowiadala wtedy "ok" i Render nie mial jak sie dowiedziec, ze
        wymienia instancje na rownie martwa.
        """
        with patch("chatbot_project.zdrowie._baza_odpowiada", return_value=False):
            odpowiedz = client.get("/health/")

        assert odpowiedz.status_code == 503
        dane = odpowiedz.json()
        assert dane["status"] == "error"
        assert dane["stan"] == "awaria"
        assert dane["baza"] is False

    def test_lezacy_broker_nie_ubija_uslugi(self, client):
        """
        Swiadoma decyzja: brak Redisa NIE psuje kodu odpowiedzi.

        Bez brokera staja zadania w tle, ale panel i czat odpowiadaja dalej.
        Ubicie z tego powodu dzialajacej instancji zamienicby czesciowa awarie
        w pelna. Stan zadan widac w tresci i - dokladniej - na ekranie
        "Stan systemu" w panelu.
        """
        with patch("chatbot_project.zdrowie._broker_odpowiada", return_value=False):
            odpowiedz = client.get("/health/")

        assert odpowiedz.status_code == 200
        dane = odpowiedz.json()
        assert dane["stan"] == "ograniczony"
        assert dane["broker"] is False

    def test_awaria_bazy_nie_wypuszcza_szczegolow_na_zewnatrz(self, client):
        """
        Adres jest publiczny i nieuwierzytelniony.

        Komunikat wyjatku z bazy potrafi zawierac nazwe hosta, port i uzytkownika
        - to za duzo dla kogos, kto tylko odpytuje adres. Szczegoly ida do logu.
        """
        with patch(
            "chatbot_project.zdrowie.connection.cursor",
            side_effect=RuntimeError("could not connect to server: db.wewnetrzny:5432"),
        ):
            odpowiedz = client.get("/health/")

        assert odpowiedz.status_code == 503
        assert "5432" not in odpowiedz.content.decode()
        assert "wewnetrzny" not in odpowiedz.content.decode()

    def test_niedostepny_broker_nie_wiesza_odpowiedzi(self, client):
        """
        Domyslne zachowanie Celery przy nieosiagalnym brokerze to kilka prob
        z narastajacym odstepem. Bez `max_retries=0` sprawdzenie stanu wisialoby
        kilkadziesiat sekund, a monitoring uznalby cisze za awarie CALEJ uslugi
        - czyli przyrzad sam wywolalby falszywy alarm.
        """
        with patch("chatbot_project.zdrowie.connection.cursor"):
            with patch("celery.Celery.connection", side_effect=OSError("brak trasy")):
                odpowiedz = client.get("/health/")

        assert odpowiedz.status_code == 200
        assert odpowiedz.json()["broker"] is False


@pytest.mark.django_db
class TestWersji:
    def test_odpowiedz_mowi_co_jest_wdrozone(self, client):
        """
        Do tej pory nie dalo sie odpowiedziec na pytanie „co jest na
        produkcji" inaczej niz przez porownywanie commitow z data wdrozenia
        w panelu hostingu. Przy zgloszeniu od klienta pierwszy krok - czy on
        w ogole ma juz poprawke - zaczynal sie od tego porownania.
        """
        from chatbot_project.wersja import WERSJA

        with patch("chatbot_project.zdrowie._broker_odpowiada", return_value=True):
            dane = client.get("/health/").json()

        assert dane["wersja"] == WERSJA

    def test_wersja_ma_ksztalt_semantyczny(self):
        # Numer, ktory nie daje sie porownac, nie mowi "nowsza czy starsza".
        import re

        from chatbot_project.wersja import WERSJA

        assert re.fullmatch(r"\d+\.\d+\.\d+", WERSJA), WERSJA

    def test_wersja_zgadza_sie_z_najnowszym_wpisem_w_changelogu(self):
        """
        Najważniejszy test w tym pliku.

        Wersja i changelog rozjezdzaja sie przy pierwszym posiechu, a wtedy
        numer w /health/ przestaje cokolwiek znaczyc: mowi, ze wdrozono 1.2.0,
        a nie da sie sprawdzic, co w tej wersji bylo.
        """
        import re
        from pathlib import Path

        from chatbot_project.wersja import WERSJA

        changelog = (Path(__file__).resolve().parents[2] / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )
        wydania = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, flags=re.MULTILINE)

        assert wydania, "CHANGELOG.md nie zawiera zadnego wydania"
        assert wydania[0] == WERSJA, (
            f"wersja w kodzie to {WERSJA}, a najnowszy wpis w CHANGELOG.md to {wydania[0]}"
        )
