"""
Kontrola kopii ma krzyczeć także wtedy, gdy kopii nie ma w ogóle.

Kategoria ryzyka: CISZA ZAMIAST ALARMU. Monitor kopii psuje się inaczej niż
reszta systemu: nie wywraca się, tylko milczy. Pusty magazyn, zatrzymany
harmonogram i harmonogram działający poprawnie wyglądają z zewnątrz tak samo -
nic się nie dzieje. Dlatego każda z tych kontrol musi kończyć się błędem przy
zerowej liczbie kopii, a nie sukcesem „nie ma czego sprawdzać".

Drugi wątek: pełna kopia (`backup_full`, format `.saas`) nie miała dotąd żadnej
kontroli, która sama znajdzie najnowszą - `verify_full_backup` wymaga podania
nazwy. Do harmonogramu to się nie nadaje, więc pełne kopie były poza monitorem.

Trzeci: kontrola uruchamiana na tym samym hostingu co kopia nie wykryje awarii
tego hostingu ani zatrzymania obu harmonogramów. `kontrola_obecnosci_kopii`
działa bez klucza szyfrowania właśnie po to, żeby dało się ją uruchomić
z zewnątrz - i te testy pilnują, że nie udaje kontroli treści.
"""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command

from accounts.backups import backup_cipher
from accounts.full_backups import NAZWA_PELNEJ_KOPII, nazwa_nowej_pelnej_kopii
from accounts.tests.test_backup_monitoring import add_backup
from accounts.tests.test_full_backups import bundle, change_manifest, rewrite, seed  # noqa: F401
from chatbot_project.storage import PrivateS3Storage

pytestmark = pytest.mark.django_db(transaction=True)

PELNA = "full-backups"


class Obiekty(dict):
    """Zawartość magazynu plus daty zapisu, trzymane osobno jak w R2."""

    def __init__(self):
        super().__init__()
        self.zapisy = {}


@pytest.fixture
def magazyn(settings, monkeypatch):
    """Atrapa prywatnego magazynu, która - inaczej niż R2 - zna prefiksy."""
    settings.STORAGES = {
        **settings.STORAGES,
        "private_backups": {
            "BACKEND": "chatbot_project.storage.PrivateS3Storage",
            "OPTIONS": {"bucket_name": "synthetic", "access_key": "test", "secret_key": "test"},
        },
    }
    obiekty = Obiekty()
    zapisy = obiekty.zapisy

    def listdir(self, path):
        prefiks = f"{path}/"
        return [], [k[len(prefiks) :] for k in obiekty if k.startswith(prefiks)]

    def open_file(self, name, mode="rb"):
        return ContentFile(obiekty[name])

    def modified(self, name):
        if name not in zapisy:
            raise NotImplementedError("magazyn nie podaje daty zapisu")
        return zapisy[name]

    monkeypatch.setattr(PrivateS3Storage, "listdir", listdir)
    monkeypatch.setattr(PrivateS3Storage, "open", open_file)
    monkeypatch.setattr(PrivateS3Storage, "get_modified_time", modified)
    return obiekty


def dodaj_pelna(obiekty, *, wiek_godzin=0, tresc=None, nazwa=None):
    surowa, _ = bundle()
    if wiek_godzin:
        stary = datetime.now(UTC) - timedelta(hours=wiek_godzin)
        surowa = rewrite(
            surowa,
            lambda wpisy: change_manifest(
                wpisy, lambda meta: meta.update(snapshot_at=stary.isoformat())
            ),
        )
    nazwa = nazwa or nazwa_nowej_pelnej_kopii(datetime.now(UTC))
    obiekty[nazwa] = tresc if tresc is not None else surowa.getvalue()
    obiekty.zapisy[nazwa] = datetime.now(UTC)
    return nazwa


def wynik(polecenie, **opcje):
    strumien = io.StringIO()
    call_command(polecenie, stdout=strumien, **opcje)
    return json.loads(strumien.getvalue())


class TestPelnejKopii:
    def test_najnowsza_kopia_jest_znajdowana_bez_podawania_nazwy(self, seed, magazyn):
        nazwa = dodaj_pelna(magazyn)

        odpowiedz = wynik("kontrola_pelnej_kopii")

        assert odpowiedz["status"] == "ok"
        assert odpowiedz["name"] == nazwa
        assert odpowiedz["files"] == 2

    def test_brak_jakiejkolwiek_kopii_to_blad_a_nie_cisza(self, seed, magazyn):
        # Harmonogram, który nigdy nie ruszył. Sukces w tym miejscu znaczyłby,
        # że po wdrożeniu bez skonfigurowanego zadania kopii monitor świeci
        # na zielono, dopóki ktoś nie zapyta wprost.
        with pytest.raises(CommandError, match="Brak pełnych kopii"):
            call_command("kontrola_pelnej_kopii")

    def test_kopia_starsza_niz_prog_konczy_sie_bledem(self, seed, magazyn):
        dodaj_pelna(magazyn, wiek_godzin=40 * 24)

        with pytest.raises(CommandError):
            call_command("kontrola_pelnej_kopii", max_age_hours=744)

    def test_uszkodzona_najnowsza_nie_cofa_sie_do_starszej_dobrej(self, seed, magazyn):
        dodaj_pelna(magazyn, nazwa=f"{PELNA}/full-20260101-000000-{'a' * 32}.saas")
        dodaj_pelna(
            magazyn, tresc=b"USZKODZONE", nazwa=f"{PELNA}/full-20260901-000000-{'b' * 32}.saas"
        )

        # Cofnięcie się do starszej kopii dałoby zielony wynik po awarii
        # ostatniego przebiegu - czyli dokładnie wtedy, kiedy ma być czerwony.
        with pytest.raises(CommandError):
            call_command("kontrola_pelnej_kopii")

    def test_nazwa_zapisywana_przez_backup_full_pasuje_do_wzorca_kontroli(self):
        # Rozjazd tych dwóch miejsc byłby cichy: kontrola przestałaby widzieć
        # nowe kopie i alarmowała dopiero po przekroczeniu progu wieku przez
        # ostatnią, którą jeszcze rozpoznaje.
        nazwa = nazwa_nowej_pelnej_kopii(datetime.now(UTC))

        assert NAZWA_PELNEJ_KOPII.fullmatch(nazwa.split("/", 1)[1])


class TestObecnosciKopii:
    def test_bez_klucza_szyfrowania_dziala_dalej(self, seed, magazyn, settings):
        # Cała racja bytu tej kontroli: ma chodzić tam, gdzie klucza nie ma.
        add_backup(magazyn)
        dodaj_pelna(magazyn)
        settings.BACKUP_ENCRYPTION_KEY = ""

        odpowiedz = wynik("kontrola_obecnosci_kopii")

        assert odpowiedz["status"] == "ok"
        assert odpowiedz["dzienna"]["wiek_godzin"] < 1
        assert odpowiedz["pelna"]["wiek_godzin"] < 1

    def test_pusty_katalog_kopii_dziennych_to_blad(self, seed, magazyn):
        dodaj_pelna(magazyn)

        with pytest.raises(CommandError, match="ani jednej kopii"):
            call_command("kontrola_obecnosci_kopii")

    def test_pusty_katalog_pelnych_kopii_to_blad(self, seed, magazyn):
        add_backup(magazyn)

        with pytest.raises(CommandError, match="ani jednej kopii"):
            call_command("kontrola_obecnosci_kopii")

    def test_stara_kopia_z_nowa_nazwa_nie_uchodzi_za_swieza(self, seed, magazyn):
        # Nazwę nadaje ten, kto zapisuje plik. Gdyby wiek brał się z samej
        # nazwy, przemianowanie starego obiektu uciszałoby alarm.
        nazwa = dodaj_pelna(magazyn)
        magazyn.zapisy[nazwa] = datetime.now(UTC) - timedelta(days=40)
        add_backup(magazyn)

        with pytest.raises(CommandError, match="próg"):
            call_command("kontrola_obecnosci_kopii")

    def test_data_z_przyszlosci_konczy_sie_bledem(self, seed, magazyn):
        add_backup(magazyn)
        nazwa = dodaj_pelna(magazyn)
        przyszlosc = datetime.now(UTC) + timedelta(days=2)
        magazyn.zapisy[nazwa] = przyszlosc
        magazyn[f"{PELNA}/full-{przyszlosc:%Y%m%d-%H%M%S}-{'c' * 32}.saas"] = magazyn.pop(nazwa)
        magazyn.zapisy[f"{PELNA}/full-{przyszlosc:%Y%m%d-%H%M%S}-{'c' * 32}.saas"] = przyszlosc

        with pytest.raises(CommandError, match="przyszłości"):
            call_command("kontrola_obecnosci_kopii")

    def test_nie_udaje_kontroli_tresci(self, seed, magazyn):
        # Umyślnie: ta kontrola odpowiada tylko na pytanie "czy coś się pojawiło".
        # Gdyby próbowała czytać treść, potrzebowałaby klucza odszyfrowującego
        # wszystkie kopie - a wtedy trzeba by go wynieść poza Rendera, czyli
        # rozszerzyć krąg miejsc, w których leży. Treści pilnują kontrole
        # z kluczem: `check_backup` i `kontrola_pelnej_kopii`.
        add_backup(magazyn)
        dodaj_pelna(magazyn, tresc=b"TO NIE JEST ZADNA KOPIA")

        assert wynik("kontrola_obecnosci_kopii")["status"] == "ok"
        with pytest.raises(CommandError):
            call_command("kontrola_pelnej_kopii")

    def test_mozna_sprawdzac_samo_archiwum_pelnych_kopii(self, seed, magazyn):
        # Wariant przyjęty 17.09.2026: pełna kopia raz w miesiącu, bez kopii
        # dziennych. Archiwum, do którego świadomie nic nie trafia, ma dać się
        # pominąć - inaczej monitor jest czerwony z powodu decyzji, nie awarii,
        # a taki alarm nikt po tygodniu nie czyta.
        dodaj_pelna(magazyn)

        odpowiedz = wynik("kontrola_obecnosci_kopii", archiwa=["pelna"])

        assert odpowiedz["sprawdzone"] == ["pelna"]
        assert "dzienna" not in odpowiedz
        assert odpowiedz["pelna"]["wiek_godzin"] < 1

    def test_pominiete_archiwum_nie_udaje_sprawdzonego(self, seed, magazyn):
        # Zielona odpowiedź musi mówić, czego dotyczy. Bez tego raport
        # z pominiętym archiwum wygląda identycznie jak raport z pełnej kontroli.
        dodaj_pelna(magazyn)
        add_backup(magazyn)

        assert wynik("kontrola_obecnosci_kopii")["sprawdzone"] == ["dzienna", "pelna"]
        assert wynik("kontrola_obecnosci_kopii", archiwa=["pelna"])["sprawdzone"] == ["pelna"]

    def test_wybrane_archiwum_dalej_alarmuje_o_braku(self, seed, magazyn):
        # Pominięcie jednego archiwum nie może rozluźnić kontroli drugiego.
        add_backup(magazyn)

        with pytest.raises(CommandError, match="ani jednej kopii"):
            call_command("kontrola_obecnosci_kopii", archiwa=["pelna"])

    def test_magazyn_bez_daty_zapisu_dalej_dziala(self, seed, magazyn):
        # Token tylko do listowania może nie mieć prawa do odczytu metadanych
        # obiektu. Zostaje wtedy data z nazwy - z adnotacją w wyniku, żeby
        # w raporcie było widać, na czym oparto wiek.
        add_backup(magazyn)
        nazwa = dodaj_pelna(magazyn)
        magazyn.zapisy.pop(nazwa)

        odpowiedz = wynik("kontrola_obecnosci_kopii")

        assert odpowiedz["pelna"]["data_zapisu_znana"] is False


def test_zip_pelnej_kopii_nie_jest_zwyklym_archiwum(seed, magazyn):
    # Kontrola pozytywna dla atrapy magazynu: gdyby zapisywała cokolwiek innego
    # niż prawdziwą kopię, wszystkie testy wyżej sprawdzałyby atrapę, nie kod.
    nazwa = dodaj_pelna(magazyn)

    with zipfile.ZipFile(io.BytesIO(magazyn[nazwa])) as archiwum:
        assert "manifest.fernet" in archiwum.namelist()
        assert backup_cipher().decrypt(archiwum.read("manifest.fernet"))
