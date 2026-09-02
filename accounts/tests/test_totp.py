"""
Zgodność implementacji TOTP z RFC 6238.

To jest cały powód, dla którego wolno było napisać ten algorytm samemu:
RFC publikuje wektory testowe, więc poprawność da się UDOWODNIĆ, a nie
założyć. Jeśli te liczby się zgadzają, kody wygenerowane tutaj są tymi
samymi, które pokaże Google Authenticator, 1Password i każda inna aplikacja
uwierzytelniająca - bo wszystkie liczą je z tej samej specyfikacji.

Wektory pochodzą z RFC 6238, dodatek B, wariant HMAC-SHA1.
"""

import base64

import pytest

from accounts import totp

#: Sekret z RFC: ciąg ASCII "12345678901234567890", podany tam jako bajty.
#: Nasza implementacja przyjmuje base32, więc przeliczamy - to samo 20 bajtów.
SEKRET_RFC = base64.b32encode(b"12345678901234567890").decode("ascii")


class TestZgodnosciZRFC:
    @pytest.mark.parametrize(
        "chwila,oczekiwany",
        [
            (59, "94287082"),
            (1111111109, "07081804"),
            (1111111111, "14050471"),
            (1234567890, "89005924"),
            (2000000000, "69279037"),
            (20000000000, "65353130"),
        ],
    )
    def test_wektory_z_dodatku_B(self, chwila, oczekiwany):
        # RFC podaje kody osmiocyfrowe; w produkcie uzywamy szesciu, ale
        # algorytm jest ten sam - roznica jest wylacznie w dzieleniu modulo.
        assert totp.kod(SEKRET_RFC, chwila=chwila, cyfr=8) == oczekiwany

    def test_kod_szesciocyfrowy_to_koncowka_osmiocyfrowego(self):
        # Sprawdzenie, ze skrocenie do szesciu cyfr nie jest osobna sciezka,
        # tylko tym samym wynikiem wzietym modulo mniejsza potega dziesiatki.
        osiem = totp.kod(SEKRET_RFC, chwila=59, cyfr=8)
        szesc = totp.kod(SEKRET_RFC, chwila=59, cyfr=6)

        assert szesc == osiem[-6:]


class TestOknaCzasowego:
    def test_kod_z_poprzedniego_kroku_jest_akceptowany(self):
        # Uzytkownik przepisuje kod recznie i zdarza mu sie trafic w moment
        # zmiany. Zero tolerancji odrzucaloby poprawne kody.
        teraz = 1_700_000_000
        poprzedni = totp.kod(SEKRET_RFC, chwila=teraz - totp.KROK_SEKUND)

        assert totp.zweryfikuj(SEKRET_RFC, poprzedni, chwila=teraz) is not None

    def test_kod_sprzed_dwoch_krokow_jest_odrzucany(self):
        # Okno musi sie gdzies konczyc - inaczej przechwycony kod dziala
        # dowolnie dlugo.
        teraz = 1_700_000_000
        stary = totp.kod(SEKRET_RFC, chwila=teraz - 3 * totp.KROK_SEKUND)

        assert totp.zweryfikuj(SEKRET_RFC, stary, chwila=teraz) is None

    def test_weryfikacja_zwraca_numer_kroku_a_nie_prawde(self):
        """
        Numer kroku jest tu istotny, nie kosmetyczny.

        Wywolujacy musi go zapamietac, zeby odrzucic PONOWNE uzycie tego
        samego kodu. Zwracanie True zamykaloby te droge: kod podejrzany przez
        ramie albo przechwycony na falszywej stronie logowania dzialalby przez
        cale swoje okno.
        """
        teraz = 1_700_000_000
        biezacy = totp.kod(SEKRET_RFC, chwila=teraz)

        krok = totp.zweryfikuj(SEKRET_RFC, biezacy, chwila=teraz)

        assert krok == int(teraz) // totp.KROK_SEKUND


class TestOdpornosci:
    @pytest.mark.parametrize("smiec", ["", "   ", "abcdef", "12345", "1234567", None])
    def test_smieci_nie_przechodza(self, smiec):
        assert totp.zweryfikuj(SEKRET_RFC, smiec, chwila=1_700_000_000) is None

    def test_kod_z_innego_sekretu_nie_przechodzi(self):
        teraz = 1_700_000_000
        inny = totp.nowy_sekret()

        cudzy = totp.kod(inny, chwila=teraz)

        assert totp.zweryfikuj(SEKRET_RFC, cudzy, chwila=teraz) is None


class TestSekretu:
    def test_nowy_sekret_daje_sie_uzyc(self):
        sekret = totp.nowy_sekret()
        teraz = 1_700_000_000

        assert totp.zweryfikuj(sekret, totp.kod(sekret, chwila=teraz), chwila=teraz) is not None

    def test_dwa_sekrety_sa_rozne(self):
        assert totp.nowy_sekret() != totp.nowy_sekret()

    def test_adres_dla_aplikacji_niesie_sekret_i_wydawce(self):
        sekret = totp.nowy_sekret()

        adres = totp.adres_do_aplikacji(sekret, "szef@rowerownia.pl", "SM-art Chat")

        assert adres.startswith("otpauth://totp/")
        assert f"secret={sekret}" in adres
        # Wydawca decyduje o nazwie, pod ktora wpis pojawi sie w aplikacji -
        # bez niego uzytkownik z kilkoma kontami nie wie, ktory kod jest czyj.
        assert "issuer=SM-art%20Chat" in adres
