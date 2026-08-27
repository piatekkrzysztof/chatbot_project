"""
Kontrola konfiguracji poczty.

Testy odtwarzają dwie awarie, które realnie wystąpiły na produkcji i obie
przeszły przez poprzednie sprawdzenie bez słowa, bo pytało wyłącznie
o obecność zmiennych. Każda kosztowała osobną rundę diagnozy na żywym
systemie, przy zapytaniu od klienta czekającym w bazie.
"""

from types import SimpleNamespace

import pytest

from chat.kontrola_poczty import problemy_z_konfiguracja

SMTP = "django.core.mail.backends.smtp.EmailBackend"


def ustawienia(**zmiany):
    """Poprawna konfiguracja, w której test psuje jedną rzecz."""
    baza = dict(
        EMAIL_BACKEND=SMTP,
        EMAIL_HOST="smtp.resend.com",
        EMAIL_HOST_PASSWORD="re_klucz_api",
        DEFAULT_FROM_EMAIL="powiadomienia@agencjasm-art.pl",
    )
    baza.update(zmiany)
    return SimpleNamespace(**baza)


class TestPoprawnejKonfiguracji:
    def test_komplet_nie_budzi_zastrzezen(self):
        assert problemy_z_konfiguracja(ustawienia()) == []

    def test_nadawca_z_nazwa_jest_dopuszczalny(self):
        """'Sm-art <adres>' to poprawna i częsta wartość tej zmiennej.
        Sam validate_email ją odrzuca, więc adres trzeba najpierw rozbić —
        bez tego kontrola krzyczałaby na działającą konfigurację."""
        assert (
            problemy_z_konfiguracja(
                ustawienia(DEFAULT_FROM_EMAIL="Sm-art <powiadomienia@agencjasm-art.pl>")
            )
            == []
        )

    def test_backend_konsolowy_nic_nie_sprawdza(self):
        """Bez połączenia ze światem adres nadawcy i host nie mają znaczenia —
        inaczej każde uruchomienie lokalne sypałoby ostrzeżeniami."""
        assert (
            problemy_z_konfiguracja(
                SimpleNamespace(
                    EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
                    EMAIL_HOST="",
                    EMAIL_HOST_PASSWORD="",
                    DEFAULT_FROM_EMAIL="",
                )
            )
            == []
        )


class TestAwariiZProdukcji:
    def test_nadawca_z_podkreslnikiem_w_domenie(self):
        """Worker miał 'powiadomienia@agencjasm_art.pl'. Połączenie i logowanie
        przechodziły, serwer odrzucał dopiero kopertę błędem 501 — czyli
        powiadomienie ginęło już po tym, jak wszystko wyglądało dobrze."""
        problemy = problemy_z_konfiguracja(
            ustawienia(DEFAULT_FROM_EMAIL="powiadomienia@agencjasm_art.pl")
        )

        assert len(problemy) == 1
        assert "DEFAULT_FROM_EMAIL" in problemy[0]

    def test_host_ze_schematem_i_ukosnikami(self):
        """Częsty odruch przy wklejaniu z dokumentacji dostawcy."""
        problemy = problemy_z_konfiguracja(ustawienia(EMAIL_HOST="https://smtp.resend.com/"))

        assert len(problemy) == 1
        assert "EMAIL_HOST" in problemy[0]

    def test_host_bez_kropki(self):
        problemy = problemy_z_konfiguracja(ustawienia(EMAIL_HOST="smtp"))

        assert len(problemy) == 1
        assert "EMAIL_HOST" in problemy[0]

    def test_brak_hasla(self):
        problemy = problemy_z_konfiguracja(ustawienia(EMAIL_HOST_PASSWORD=""))

        assert len(problemy) == 1
        assert "EMAIL_HOST_PASSWORD" in problemy[0]

    def test_kilka_bledow_naraz_jest_wypisanych_osobno(self):
        """Przy dwóch pomyłkach naraz poprawienie jednej nie może wyglądać
        na naprawę całości."""
        problemy = problemy_z_konfiguracja(
            ustawienia(EMAIL_HOST="", DEFAULT_FROM_EMAIL="bez-malpy")
        )

        assert len(problemy) == 2


class TestGranicySprawdzenia:
    def test_literowka_w_nazwie_hosta_NIE_jest_wykrywana(self):
        """
        Uczciwe udokumentowanie granicy: 'stmp.resend.com' to poprawnie
        zbudowana nazwa domenowa i statycznie nie da się jej odróżnić od
        prawdziwej. Ta awaria — pierwsza z dwóch produkcyjnych — wychodzi
        dopiero przy realnym połączeniu, czyli w komendzie `sprawdz_poczte`.

        Test istnieje po to, żeby nikt nie założył, że sama kontrola startowa
        wystarcza.
        """
        assert problemy_z_konfiguracja(ustawienia(EMAIL_HOST="stmp.resend.com")) == []


@pytest.mark.django_db
class TestOstrzezeniaPrzyStarcie:
    def test_ready_loguje_kazdy_problem(self, caplog):
        """Sprawdzenie ma się wykonać w każdym procesie — web, workerze
        i zegarze — bo każda usługa na Renderze ma własny, ręcznie wklepany
        komplet zmiennych i to właśnie one się rozjechały."""
        from django.apps import apps
        from django.test import override_settings

        with override_settings(
            EMAIL_BACKEND=SMTP,
            EMAIL_HOST="smtp.resend.com",
            EMAIL_HOST_PASSWORD="re_klucz",
            DEFAULT_FROM_EMAIL="powiadomienia@agencjasm_art.pl",
        ):
            with caplog.at_level("WARNING"):
                apps.get_app_config("chat").ready()

        assert any("DEFAULT_FROM_EMAIL" in zapis.getMessage() for zapis in caplog.records)


class TestSpojnosciBlueprintu:
    """
    render.yaml nie tworzy usług sam z siebie i nie przenosi wartości
    oznaczonych `sync: false` — ale ma pokazywać, JAKIE zmienne istnieją
    i gdzie muszą być. Rozjazd między usługami w samym pliku znaczyłby, że
    dokumentacja przestała ostrzegać przed problemem, dla którego powstała.
    """

    def test_obie_uslugi_deklaruja_ten_sam_komplet_zmiennych_poczty(self):
        import yaml

        with open("render.yaml", encoding="utf-8") as plik:
            blueprint = yaml.safe_load(plik)

        komplety = {
            usluga["name"]: sorted(
                z["key"]
                for z in usluga["envVars"]
                if z["key"].startswith(("EMAIL_", "DEFAULT_FROM_EMAIL"))
            )
            for usluga in blueprint["services"]
            if usluga["type"] in ("web", "worker")
        }

        assert len(komplety) == 2, f"spodziewane dwie usługi, są: {list(komplety)}"
        web, worker = komplety.values()
        assert web == worker, f"rozjazd zmiennych poczty między usługami: {komplety}"
        # Worker realnie wysyła powiadomienia, więc nadawca musi być i tam
        assert "DEFAULT_FROM_EMAIL" in worker
        assert "EMAIL_HOST" in worker
