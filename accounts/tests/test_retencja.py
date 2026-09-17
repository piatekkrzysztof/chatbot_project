"""
Usuwanie danych po okresie przechowywania.

Kategoria ryzyka: DANE, KTÓRYCH NIE DA SIĘ ODZYSKAĆ. Retencja jest jedyną
operacją w tym systemie, która kasuje dane klientów bez pytania i bez śladu -
kopia zapasowa pomaga tylko wtedy, gdy ktoś zauważy pomyłkę przed rotacją kopii.
Dlatego testy pilnują trzech rzeczy w tej kolejności:

1. **Granica.** Wiersz tuż przed terminem zostaje, tuż po - znika. Pomyłka o
   jeden dzień w warunku jest niewidoczna w przeglądzie i widoczna dopiero
   wtedy, gdy zabraknie wpisu, który miał być dowodem.
2. **Co nie znika nigdy.** Ważne zaproszenie, ważna sesja, powiadomienie
   czekające na wysyłkę. Każde z nich usunięte oznacza odebrany dostęp albo
   zgubiony sygnał o przejęciu konta.
3. **Przebieg przerwany w połowie.** Usuwanie idzie partiami, więc awaria
   zostawia bazę w stanie pośrednim. Ma być spójny, a następny przebieg ma
   dokończyć robotę.

Czwarta rzecz, wynikająca z dzisiejszych doświadczeń: raport i usuwanie liczą
z tego samego modułu, a ten test porównuje reguły z zachowaniem komend `purge_*`,
które działały tu wcześniej. Rozjazd tych dwóch źródeł byłby cichy.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts import retencja
from accounts.models import InvitationToken, MfaChallenge, PendingRegistration, WpisDziennika
from accounts.security_notifications import PasswordNotification
from accounts.sessions import LoginSession
from chatbot_project.celery import app as aplikacja_celery

pytestmark = pytest.mark.django_db

GODZINA = timedelta(hours=1)


def wpis_dziennika(wiek):
    wpis = WpisDziennika.objects.create(metoda="DELETE", sciezka="/api/faq/1/", status=204)
    WpisDziennika.objects.filter(pk=wpis.pk).update(czas=timezone.now() - wiek)
    return wpis


def zaproszenie(tenant, *, wiek=timedelta(), dlugosc="1d", uzyte=0, miejsc=1):
    wpis = InvitationToken.objects.create(
        tenant=tenant, email="ktos@example.com", duration=dlugosc, users=uzyte, max_users=miejsc
    )
    InvitationToken.objects.filter(pk=wpis.pk).update(created_at=timezone.now() - wiek)
    return wpis


def sesja(uzytkownik, *, wygasla_przed=None):
    teraz = timezone.now()
    return LoginSession.objects.create(
        user=uzytkownik,
        password_fingerprint="x" * 64,
        expires_at=teraz - wygasla_przed if wygasla_przed else teraz + 7 * timedelta(days=1),
    )


def wyzwanie(uzytkownik, *, wygaslo_przed):
    return MfaChallenge.objects.create(
        user=uzytkownik, fingerprint="f", expires_at=timezone.now() - wygaslo_przed
    )


def rejestracja(adres, wiek):
    teraz = timezone.now()
    wpis = PendingRegistration.objects.create(
        email=adres, expires_at=teraz + timedelta(days=1), window_start=teraz
    )
    PendingRegistration.objects.filter(pk=wpis.pk).update(created_at=teraz - wiek)
    return wpis


def powiadomienie(uzytkownik, *, wiek, status=PasswordNotification.Status.SENT):
    return PasswordNotification.objects.create(
        user=uzytkownik,
        recipient="ktos@example.com",
        created_at=timezone.now() - wiek,
        status=status,
    )


def test_okresy_sa_tymi_zatwierdzonymi():
    """
    Wartości zatwierdzone przez właściciela 17.09.2026, na liczbach z raportu
    z produkcji. Testy granic biorą okres ze stałej, więc same z siebie nie
    zauważą, że ktoś tę stałą zmienił - a zmiana okresu jest decyzją o danych
    klientów, nie porządkami w kodzie. Ten test ma ją zatrzymać i zmusić do
    świadomego przepisania razem z dokumentacją.
    """
    assert retencja.OKRESY == {
        "dziennik": timedelta(days=365),
        "zaproszenia": timedelta(days=30),
        "sesje": timedelta(days=1),
        "wyzwania_mfa": timedelta(days=1),
        "rejestracje": timedelta(days=7),
        "powiadomienia": timedelta(days=90),
    }


class TestGranicy:
    """Wiersz tuż przed terminem zostaje, tuż po - znika."""

    def test_dziennik(self):
        okres = retencja.OKRESY["dziennik"]
        wpis_dziennika(okres - GODZINA)
        stary = wpis_dziennika(okres + GODZINA)

        assert retencja.usun("dziennik") == 1
        assert list(WpisDziennika.objects.values_list("pk", flat=True)) != [stary.pk]
        assert WpisDziennika.objects.count() == 1

    def test_zaproszenia(self, tenant):
        okres = retencja.OKRESY["zaproszenia"]
        mlode = zaproszenie(tenant, wiek=okres - GODZINA, uzyte=1)
        zaproszenie(tenant, wiek=okres + GODZINA, uzyte=1)

        assert retencja.usun("zaproszenia") == 1
        assert list(InvitationToken.objects.values_list("pk", flat=True)) == [mlode.pk]

    def test_sesje(self, user):
        okres = retencja.OKRESY["sesje"]
        sesja(user, wygasla_przed=okres - GODZINA)
        sesja(user, wygasla_przed=okres + GODZINA)

        assert retencja.usun("sesje") == 1
        assert LoginSession.objects.count() == 1

    def test_wyzwania_mfa(self, user):
        okres = retencja.OKRESY["wyzwania_mfa"]
        wyzwanie(user, wygaslo_przed=okres - GODZINA)
        wyzwanie(user, wygaslo_przed=okres + GODZINA)

        assert retencja.usun("wyzwania_mfa") == 1
        assert MfaChallenge.objects.count() == 1

    def test_rejestracje(self):
        okres = retencja.OKRESY["rejestracje"]
        rejestracja("mloda@example.com", okres - GODZINA)
        rejestracja("stara@example.com", okres + GODZINA)

        assert retencja.usun("rejestracje") == 1
        assert PendingRegistration.objects.get().email == "mloda@example.com"

    def test_powiadomienia(self, user):
        okres = retencja.OKRESY["powiadomienia"]
        powiadomienie(user, wiek=okres - GODZINA)
        powiadomienie(user, wiek=okres + GODZINA)

        assert retencja.usun("powiadomienia") == 1
        assert PasswordNotification.objects.count() == 1


class TestCoNieZnikaNigdy:
    def test_wazne_zaproszenie_zostaje_mimo_wieku(self, tenant):
        # Tygodniowe zaproszenie sprzed dwóch dni: stare, ale wciąż otwiera drzwi.
        zaproszenie(tenant, wiek=timedelta(days=2), dlugosc="7d")

        assert retencja.usun("zaproszenia") == 0
        assert InvitationToken.objects.count() == 1

    def test_wazna_sesja_zostaje(self, user):
        sesja(user)

        assert retencja.usun("sesje") == 0

    def test_powiadomienie_czekajace_na_wyslanie_zostaje(self, user):
        # Stare, bo kolejka stała - ale to nadal jedyny sygnał przy przejęciu konta.
        powiadomienie(user, wiek=timedelta(days=400), status=PasswordNotification.Status.PENDING)

        assert retencja.usun("powiadomienia") == 0
        assert PasswordNotification.objects.count() == 1

    def test_wykorzystane_zaproszenie_znika_dopiero_po_okresie(self, tenant):
        # Wiek liczony od utworzenia: chwili przyjęcia zaproszenia baza nie zna.
        zaproszenie(tenant, wiek=timedelta(days=1), dlugosc="7d", uzyte=1)

        assert retencja.usun("zaproszenia") == 0


class TestPrzebiegu:
    def test_proba_niczego_nie_usuwa(self, user, tenant):
        wpis_dziennika(retencja.OKRESY["dziennik"] + GODZINA)
        sesja(user, wygasla_przed=retencja.OKRESY["sesje"] + GODZINA)

        wyniki = retencja.usun_wszystko(proba=True)

        assert wyniki["dziennik"] == 1
        assert wyniki["sesje"] == 1
        assert WpisDziennika.objects.count() == 1
        assert LoginSession.objects.count() == 1

    def test_partie_zabieraja_wszystko(self):
        for _ in range(5):
            wpis_dziennika(retencja.OKRESY["dziennik"] + GODZINA)

        assert retencja.usun("dziennik", partia=2) == 5
        assert WpisDziennika.objects.count() == 0

    def test_przebieg_przerwany_w_polowie_konczy_nastepny(self, mocker):
        # Awaria po pierwszej partii: baza ma zostać spójna, a reszta wierszy
        # czekać na kolejny przebieg. Nocne zadanie chodzi codziennie, więc
        # przerwanie kosztuje dobę, a nie ręczną naprawę.
        for _ in range(4):
            wpis_dziennika(retencja.OKRESY["dziennik"] + GODZINA)
        prawdziwy = WpisDziennika.objects.filter
        wywolania = {"ile": 0}

        def czasem_pada(*args, **kwargs):
            wywolania["ile"] += 1
            if wywolania["ile"] > 3:
                raise RuntimeError("magazyn padł w połowie")
            return prawdziwy(*args, **kwargs)

        mocker.patch.object(WpisDziennika.objects, "filter", side_effect=czasem_pada)
        with pytest.raises(RuntimeError):
            retencja.usun("dziennik", partia=1)
        mocker.stopall()

        zostalo = WpisDziennika.objects.count()
        assert 0 < zostalo < 4
        assert retencja.usun("dziennik") == zostalo
        assert WpisDziennika.objects.count() == 0


class TestZgodnosciZKomendamiSprzed:
    """Reguły muszą robić to samo, co komendy, które działały tu wcześniej."""

    def test_sesje(self, user):
        sesja(user, wygasla_przed=timedelta(days=3))
        sesja(user, wygasla_przed=timedelta(hours=2))
        sesja(user)
        obiecane = retencja.usun("sesje", proba=True)
        przed = LoginSession.objects.count()

        call_command("purge_login_sessions")

        assert obiecane == przed - LoginSession.objects.count() == 1

    def test_wyzwania_mfa(self, user):
        wyzwanie(user, wygaslo_przed=timedelta(days=3))
        wyzwanie(user, wygaslo_przed=timedelta(hours=2))
        obiecane = retencja.usun("wyzwania_mfa", proba=True)
        przed = MfaChallenge.objects.count()

        call_command("purge_mfa_challenges")

        assert obiecane == przed - MfaChallenge.objects.count() == 1

    def test_rejestracje(self):
        rejestracja("stara@example.com", timedelta(days=10))
        rejestracja("mloda@example.com", timedelta(days=2))
        obiecane = retencja.usun("rejestracje", proba=True)
        przed = PendingRegistration.objects.count()

        call_command("purge_pending_registrations")

        assert obiecane == przed - PendingRegistration.objects.count() == 1


class TestHarmonogramu:
    def test_zadanie_jest_w_harmonogramie(self):
        wpisy = {wpis["task"] for wpis in aplikacja_celery.conf.beat_schedule.values()}

        assert "accounts.tasks_retencja.sprzataj_retencje" in wpisy

    def test_zadanie_nie_zaczyna_sie_razem_ze_sprzataniem_rozmow(self):
        # Oba biją w tę samą bazę, a rozmowy potrafią usuwać najwięcej.
        pory = {
            wpis["task"]: str(wpis["schedule"])
            for wpis in aplikacja_celery.conf.beat_schedule.values()
        }

        assert pory["accounts.tasks_retencja.sprzataj_retencje"] != pory.get(
            "chat.tasks.purge_expired_conversations"
        )

    def test_zadanie_usuwa_i_zglasza_wynik(self, user, caplog):
        wpis_dziennika(retencja.OKRESY["dziennik"] + GODZINA)
        sesja(user, wygasla_przed=retencja.OKRESY["sesje"] + GODZINA)
        from accounts.tasks_retencja import sprzataj_retencje

        with caplog.at_level("INFO"):
            wynik = sprzataj_retencje()

        assert wynik["dziennik"] == 1 and wynik["sesje"] == 1
        assert WpisDziennika.objects.count() == 0
        # Zeru też trzeba dać głos: cisza w logu nie odróżnia przebiegu, który
        # nic nie znalazł, od przebiegu, którego nie było.
        assert "rejestracje=0" in caplog.text


class TestPolecenia:
    def test_dry_run_liczy_i_nie_usuwa(self, user):
        sesja(user, wygasla_przed=retencja.OKRESY["sesje"] + GODZINA)

        call_command("purge_retencja", "--dry-run")

        assert LoginSession.objects.count() == 1

    def test_jeden_rodzaj_nie_rusza_pozostalych(self, user):
        wpis_dziennika(retencja.OKRESY["dziennik"] + GODZINA)
        sesja(user, wygasla_przed=retencja.OKRESY["sesje"] + GODZINA)

        call_command("purge_retencja", "--rodzaj", "sesje")

        assert LoginSession.objects.count() == 0
        assert WpisDziennika.objects.count() == 1
