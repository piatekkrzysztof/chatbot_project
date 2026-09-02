"""
Drugi składnik: konfiguracja, logowanie dwuetapowe, kody zapasowe.

Kategoria ryzyka: DOSTĘP. Jedno konto właściciela otwiera rozmowy wszystkich
klientów firmy, więc samo hasło jest tu cienką granicą - zwłaszcza że hasła
wyciekają masowo z zupełnie innych serwisów, a ludzie ich używają ponownie.

Każdy test pilnuje obu połówek: że droga właściwa działa ORAZ że niewłaściwa
jest zamknięta. Sam pierwszy warunek przepuściłby drugi składnik, który
wygląda na włączony i przepuszcza każdy kod.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import dwuskladnikowe, totp
from accounts.models import DrugiSkladnik, KodZapasowy, Tenant

HASLO = "prawidlowe-haslo-2026"


@pytest.fixture
def wlascicielka(db, django_user_model):
    firma = Tenant.objects.create(name="Rowerownia Krakowska")
    return django_user_model.objects.create_user(
        username="szef@rowerownia.pl",
        email="szef@rowerownia.pl",
        password=HASLO,
        tenant=firma,
        role="owner",
    )


@pytest.fixture
def zalogowana(wlascicielka):
    klient = APIClient()
    klient.force_authenticate(user=wlascicielka)
    klient.credentials(HTTP_X_API_KEY=str(wlascicielka.tenant.api_key))
    return klient


def wlacz_drugi_skladnik(uzytkownik) -> DrugiSkladnik:
    """Skrót dla testów, które zaczynają od konta z już włączoną ochroną."""
    skladnik = DrugiSkladnik.objects.create(
        uzytkownik=uzytkownik, sekret=totp.nowy_sekret(), potwierdzony_od=timezone.now()
    )
    dwuskladnikowe.wygeneruj_kody_zapasowe(uzytkownik)
    return skladnik


@pytest.mark.django_db
class TestKonfiguracji:
    def test_rozpoczecie_daje_sekret_i_adres_dla_aplikacji(self, zalogowana):
        odpowiedz = zalogowana.post(reverse("2fa-rozpocznij"))

        assert odpowiedz.status_code == 201
        assert odpowiedz.data["sekret"]
        assert odpowiedz.data["adres_otpauth"].startswith("otpauth://totp/")

    def test_sam_sekret_jeszcze_nie_wlacza_ochrony(self, zalogowana, wlascicielka):
        """
        Rozdział na dwa kroki jest tu celem, nie ceremonią.

        Ktoś, kto zeskanuje kod QR i zamknie kartę, zostałby z włączoną
        ochroną i bez działającej aplikacji - czyli zamknięty na zewnątrz
        własnego konta.
        """
        zalogowana.post(reverse("2fa-rozpocznij"))

        assert not dwuskladnikowe.ma_wlaczony_drugi_skladnik(wlascicielka)
        assert zalogowana.get(reverse("2fa-stan")).data["w_trakcie_konfiguracji"] is True

    def test_potwierdzenie_wlacza_i_wydaje_kody_zapasowe(self, zalogowana, wlascicielka):
        sekret = zalogowana.post(reverse("2fa-rozpocznij")).data["sekret"]

        odpowiedz = zalogowana.post(
            reverse("2fa-potwierdz"), {"kod": totp.kod(sekret)}, format="json"
        )

        assert odpowiedz.status_code == 200
        assert len(odpowiedz.data["kody_zapasowe"]) == dwuskladnikowe.ILE_KODOW_ZAPASOWYCH
        wlascicielka.refresh_from_db()
        assert dwuskladnikowe.ma_wlaczony_drugi_skladnik(wlascicielka)

    def test_zly_kod_nie_wlacza_ochrony(self, zalogowana, wlascicielka):
        zalogowana.post(reverse("2fa-rozpocznij"))

        odpowiedz = zalogowana.post(reverse("2fa-potwierdz"), {"kod": "000000"}, format="json")

        assert odpowiedz.status_code == 400
        assert not dwuskladnikowe.ma_wlaczony_drugi_skladnik(wlascicielka)

    def test_kody_zapasowe_nie_leza_w_bazie_otwartym_tekstem(self, zalogowana):
        """
        Kod zapasowy jest równoważny drugiemu składnikowi. Lista czytelnych
        kodów w bazie znosiłaby całą ochronę: ktoś ze zrzutem bazy omijałby
        drugi składnik dla wszystkich kont naraz.
        """
        sekret = zalogowana.post(reverse("2fa-rozpocznij")).data["sekret"]
        kody = zalogowana.post(
            reverse("2fa-potwierdz"), {"kod": totp.kod(sekret)}, format="json"
        ).data["kody_zapasowe"]

        zapisane = set(KodZapasowy.objects.values_list("skrot", flat=True))
        assert not (set(kody) & zapisane)


@pytest.mark.django_db
class TestLogowania:
    def test_bez_drugiego_skladnika_logowanie_dziala_jak_dotad(self, wlascicielka):
        odpowiedz = APIClient().post(
            reverse("login"),
            {"username": wlascicielka.username, "password": HASLO},
            format="json",
        )

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["access"]

    def test_haslo_samo_nie_wystarcza_gdy_ochrona_wlaczona(self, wlascicielka):
        """
        Najważniejszy test w tym pliku. Gdyby pierwszy krok nadal wydawał
        tokeny, drugi składnik byłby dekoracją: włączony w panelu, obojętny
        przy logowaniu.
        """
        wlacz_drugi_skladnik(wlascicielka)

        odpowiedz = APIClient().post(
            reverse("login"),
            {"username": wlascicielka.username, "password": HASLO},
            format="json",
        )

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["wymaga_drugiego_skladnika"] is True
        assert "access" not in odpowiedz.data
        assert "refresh" not in odpowiedz.data

    def test_bilet_i_kod_daja_sesje(self, wlascicielka):
        skladnik = wlacz_drugi_skladnik(wlascicielka)
        klient = APIClient()
        bilet = klient.post(
            reverse("login"),
            {"username": wlascicielka.username, "password": HASLO},
            format="json",
        ).data["bilet"]

        odpowiedz = klient.post(
            reverse("login-2fa"),
            {"bilet": bilet, "kod": totp.kod(skladnik.sekret)},
            format="json",
        )

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["access"]

    def test_kod_zapasowy_tez_otwiera_sesje(self, wlascicielka):
        # Telefon ginie i to jest przewidywalne. Bez tej drogi jedyną
        # procedurą odzyskania dostępu byłby telefon do nas.
        wlacz_drugi_skladnik(wlascicielka)
        kody = dwuskladnikowe.wygeneruj_kody_zapasowe(wlascicielka)
        klient = APIClient()
        bilet = klient.post(
            reverse("login"),
            {"username": wlascicielka.username, "password": HASLO},
            format="json",
        ).data["bilet"]

        odpowiedz = klient.post(
            reverse("login-2fa"), {"bilet": bilet, "kod": kody[0]}, format="json"
        )

        assert odpowiedz.status_code == 200
        assert odpowiedz.data["access"]

    def test_kod_zapasowy_dziala_tylko_raz(self, wlascicielka):
        wlacz_drugi_skladnik(wlascicielka)
        kody = dwuskladnikowe.wygeneruj_kody_zapasowe(wlascicielka)
        klient = APIClient()

        for _ in range(2):
            bilet = klient.post(
                reverse("login"),
                {"username": wlascicielka.username, "password": HASLO},
                format="json",
            ).data["bilet"]
            ostatnia = klient.post(
                reverse("login-2fa"), {"bilet": bilet, "kod": kody[0]}, format="json"
            )

        assert ostatnia.status_code == 400

    def test_ten_sam_kod_z_aplikacji_nie_dziala_dwa_razy(self, wlascicielka):
        """
        Kod podejrzany przez ramię albo przechwycony na fałszywej stronie
        logowania musi być bezużyteczny natychmiast po pierwszym użyciu -
        a nie do końca swojego trzydziestosekundowego okna.
        """
        skladnik = wlacz_drugi_skladnik(wlascicielka)
        klient = APIClient()
        kod = totp.kod(skladnik.sekret)

        for _ in range(2):
            bilet = klient.post(
                reverse("login"),
                {"username": wlascicielka.username, "password": HASLO},
                format="json",
            ).data["bilet"]
            ostatnia = klient.post(
                reverse("login-2fa"), {"bilet": bilet, "kod": kod}, format="json"
            )

        assert ostatnia.status_code == 400

    def test_bilet_nie_otwiera_api_sam_z_siebie(self, wlascicielka):
        # Bilet niesie sam identyfikator użytkownika. Gdyby dało się nim
        # wołać API, drugi krok byłby formalnością do pominięcia.
        wlacz_drugi_skladnik(wlascicielka)
        klient = APIClient()
        bilet = klient.post(
            reverse("login"),
            {"username": wlascicielka.username, "password": HASLO},
            format="json",
        ).data["bilet"]

        klient.credentials(HTTP_AUTHORIZATION=f"Bearer {bilet}")

        assert klient.get(reverse("me")).status_code == 401

    def test_zly_bilet_jest_odrzucany(self, wlascicielka):
        wlacz_drugi_skladnik(wlascicielka)

        odpowiedz = APIClient().post(
            reverse("login-2fa"), {"bilet": "podrobiony", "kod": "123456"}, format="json"
        )

        assert odpowiedz.status_code == 401


@pytest.mark.django_db
class TestWylaczania:
    def test_wymaga_hasla_i_kodu_naraz(self, zalogowana, wlascicielka):
        """
        Porwana sesja daje dostęp do panelu, ale nie do hasła ani do telefonu.
        Gdyby wystarczyło jedno z dwojga, przejęta karta wyłączałaby ochronę.
        """
        skladnik = wlacz_drugi_skladnik(wlascicielka)

        samo_haslo = zalogowana.post(
            reverse("2fa-wylacz"), {"haslo": HASLO, "kod": "000000"}, format="json"
        )
        sam_kod = zalogowana.post(
            reverse("2fa-wylacz"),
            {"haslo": "zle", "kod": totp.kod(skladnik.sekret)},
            format="json",
        )

        assert samo_haslo.status_code == 400
        assert sam_kod.status_code == 400
        assert dwuskladnikowe.ma_wlaczony_drugi_skladnik(wlascicielka)

    def test_haslo_i_kod_wylaczaja_i_kasuja_kody_zapasowe(self, zalogowana, wlascicielka):
        skladnik = wlacz_drugi_skladnik(wlascicielka)

        odpowiedz = zalogowana.post(
            reverse("2fa-wylacz"),
            {"haslo": HASLO, "kod": totp.kod(skladnik.sekret)},
            format="json",
        )

        assert odpowiedz.status_code == 200
        wlascicielka.refresh_from_db()
        assert not dwuskladnikowe.ma_wlaczony_drugi_skladnik(wlascicielka)
        # Kody zapasowe przeżywające wyłączenie otwierałyby ochronę włączoną
        # ponownie miesiąc później.
        assert not KodZapasowy.objects.filter(uzytkownik=wlascicielka).exists()

    def test_nie_da_sie_nadpisac_dzialajacego_sekretu(self, zalogowana, wlascicielka):
        # Nadpisanie sekretu jednym żądaniem unieważniłoby aplikację, której
        # użytkownik właśnie używa - i to bez potwierdzenia hasłem.
        wlacz_drugi_skladnik(wlascicielka)

        assert zalogowana.post(reverse("2fa-rozpocznij")).status_code == 409
