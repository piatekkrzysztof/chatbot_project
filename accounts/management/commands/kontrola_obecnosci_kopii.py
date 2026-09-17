"""
Czy kopie w ogóle powstają - kontrola do uruchomienia POZA Renderem.

Po co osobne polecenie, skoro są już `check_backup` i `kontrola_pelnej_kopii`:
tamte dwa sprawdzają treść kopii, więc potrzebują klucza szyfrowania i chodzą
tam, gdzie ten klucz już jest. Kontrola uruchamiana na tym samym hostingu co
kopia nie wykryje jednak dwóch awarii, które są tu najgroźniejsze: zatrzymania
całego harmonogramu i awarii samego hostingu. Milczenie wygląda wtedy dokładnie
tak samo jak spokój.

Dlatego ta kontrola:

* **nie potrzebuje klucza szyfrowania** - wystarczy token tylko do odczytu
  i listowania magazynu kopii, więc można ją uruchomić z zewnątrz bez
  rozszerzania kręgu miejsc, w których leży klucz odszyfrowujący wszystko;
* odpowiada wyłącznie na pytanie „czy coś nowego się pojawiło". **Nie jest
  dowodem, że kopia jest kompletna i da się ją odczytać** - to zostaje przy
  kontrolach z kluczem.

Wiek liczymy ostrożnie: bierzemy starszą z dwóch dat - tej z nazwy i daty
zapisu obiektu. Samo skopiowanie obiektu odświeża datę zapisu, a nazwę da się
nadać dowolną, więc żadna z nich osobno nie wystarcza. Pusty magazyn jest
błędem, nie ciszą - harmonogram, który nigdy nie ruszył, ma wyglądać inaczej
niż harmonogram działający.
"""

import json
import math
import re
from datetime import UTC, datetime

from django.core.management.base import BaseCommand, CommandError

from accounts.backups import private_backup_storage
from accounts.full_backups import KATALOG_PELNYCH_KOPII, NAZWA_PELNEJ_KOPII

NAZWA_DZIENNEJ_KOPII = re.compile(r"kopia-[0-9]{8}-[0-9]{6}-[a-f0-9]{32}\.json\.fernet\Z")
CZAS_W_NAZWIE = re.compile(r"-([0-9]{8}-[0-9]{6})-")

ARCHIWA = {
    "dzienna": ("backups", NAZWA_DZIENNEJ_KOPII),
    "pelna": (KATALOG_PELNYCH_KOPII, NAZWA_PELNEJ_KOPII),
}


def czas_z_nazwy(nazwa):
    dopasowanie = CZAS_W_NAZWIE.search(nazwa)
    if not dopasowanie:
        raise CommandError(f"Nazwa kopii bez czytelnej daty: {nazwa}")
    return datetime.strptime(dopasowanie.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=UTC)


def data_zapisu(magazyn, sciezka):
    """Data zapisu obiektu albo None, gdy magazyn jej nie podaje."""
    try:
        zapis = magazyn.get_modified_time(sciezka)
    except Exception:
        return None
    return zapis if zapis.tzinfo else zapis.replace(tzinfo=UTC)


def sprawdz_archiwum(magazyn, katalog, wzorzec, prog_godzin, teraz):
    try:
        _, nazwy = magazyn.listdir(katalog)
    except Exception:
        raise CommandError(f"Nie można odczytać listy kopii z katalogu {katalog}.") from None
    pasujace = [nazwa for nazwa in nazwy if wzorzec.fullmatch(nazwa)]
    if not pasujace:
        raise CommandError(f"W katalogu {katalog} nie ma ani jednej kopii.")
    nazwa = max(pasujace)
    sciezka = f"{katalog}/{nazwa}"
    daty = [czas_z_nazwy(nazwa)]
    zapis = data_zapisu(magazyn, sciezka)
    if zapis is not None:
        daty.append(zapis)
    # Starsza z dat: nazwę można nadać dowolną, a data zapisu odświeża się przy
    # samym skopiowaniu obiektu. Osobno każda z nich potrafi odmłodzić kopię.
    najstarsza = min(daty)
    wiek = (teraz - najstarsza).total_seconds()
    if wiek < -60:
        raise CommandError(f"Kopia w {katalog} ma datę z przyszłości; sprawdź zegary usług.")
    if wiek > prog_godzin * 3600:
        raise CommandError(
            f"Najnowsza kopia w {katalog} ma {wiek / 3600:.1f} h, próg to {prog_godzin} h."
        )
    return {
        "nazwa": sciezka,
        "wiek_godzin": round(max(0.0, wiek) / 3600, 2),
        "data_zapisu_znana": zapis is not None,
        "kopii": len(pasujace),
    }


class Command(BaseCommand):
    help = "Czy kopie w ogóle powstają; bez klucza szyfrowania, do uruchomienia spoza Rendera."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--dzienna-godzin", type=float, default=30)
        parser.add_argument("--pelna-godzin", type=float, default=744)

    def handle(self, *args, **options):
        progi = {"dzienna": options["dzienna_godzin"], "pelna": options["pelna_godzin"]}
        for nazwa, prog in progi.items():
            if not math.isfinite(prog) or not 0 < prog <= 8760:
                raise CommandError(f"Próg {nazwa} musi być większy od 0 i nie większy niż 8760.")
        magazyn = private_backup_storage()
        teraz = datetime.now(UTC)
        wynik = {
            rodzaj: sprawdz_archiwum(magazyn, katalog, wzorzec, progi[rodzaj], teraz)
            for rodzaj, (katalog, wzorzec) in ARCHIWA.items()
        }
        self.stdout.write(json.dumps({"status": "ok", **wynik}, sort_keys=True))
