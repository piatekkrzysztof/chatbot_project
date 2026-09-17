"""
Baza wiedzy większa niż limit planu: co wolno, a czego nie.

Kategoria ryzyka: KLIENT ZABLOKOWANY WE WŁASNYCH DANYCH. Limit powstał po to,
żeby baza nie rosła ponad plan. Ale przekroczyć go można nie tylko dodając -
wystarczy zejść z planu Pro na Start i tego samego dnia mieć 40 MB przy limicie
5 MB. Nikt nic nie dodał, a stan jest „ponad limit".

Od tej chwili warunek `obecnie - zastępowane + dodawane <= limit` odrzuca
wszystko: odświeżenie podstrony tej samej wielkości, zamianę dużej strony na
mniejszą, każdą operację zmniejszającą bazę. Klient nie może ani zmniejszyć
bazy przez zamianę treści, ani odświeżyć cennika, który się zdezaktualizował -
a bot i tak dalej odpowiada ze wszystkich 40 MB, bo wyszukiwanie limitu nie zna.

Reguła, która ma obowiązywać: **wolno wszystko, co nie powiększa bazy ponad to,
co już jest.** Blokujemy wzrost, nie utrzymanie i nie zmniejszanie.
"""

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Subscription
from documents.models import Document
from documents.validators import MB, sprawdz_limit_bazy_wiedzy

pytestmark = pytest.mark.django_db


@pytest.fixture
def firma_po_obnizeniu(tenant):
    """Firma z 8 MB wiedzy na planie Start (limit 5 MB) - jak po zejściu z Pro."""
    Subscription.objects.create(
        tenant=tenant,
        plan_type="start",
        is_active=True,
        start_date=timezone.now().date(),
        end_date=timezone.now().date(),
    )
    Document.objects.create(tenant=tenant, name="Cennik", content="c" * (6 * MB))
    Document.objects.create(tenant=tenant, name="Regulamin", content="r" * (2 * MB))
    return tenant


def test_odswiezenie_strony_tej_samej_wielkosci_przechodzi(firma_po_obnizeniu):
    # Podstrona odświeżana przez crawler: tyle samo znaków, inna treść.
    # Blokada tutaj zamraża wiedzę klienta na wersji sprzed obniżenia planu,
    # a bot i tak odpowiada ze starej - nikt na tym nie zyskuje.
    sprawdz_limit_bazy_wiedzy(firma_po_obnizeniu, "n" * (6 * MB), zastepowany_tekst="c" * (6 * MB))


def test_zmniejszanie_bazy_przechodzi_takze_gdy_nie_dociaga_do_limitu(firma_po_obnizeniu):
    # Zamiana 6 MB na 4 MB: baza schodzi z 8 MB na 6 MB, czyli w dobrą stronę,
    # ale wciąż jest ponad limitem 5 MB. Warunek liczący tylko wynik końcowy
    # odrzucał taki krok - klient nie mógł zejść do limitu małymi krokami,
    # tylko skokiem albo przez kasowanie dokumentów.
    sprawdz_limit_bazy_wiedzy(firma_po_obnizeniu, "n" * (4 * MB), zastepowany_tekst="c" * (6 * MB))


def test_zejscie_ponizej_limitu_jednym_krokiem_dalej_przechodzi(firma_po_obnizeniu):
    sprawdz_limit_bazy_wiedzy(firma_po_obnizeniu, "n" * (1 * MB), zastepowany_tekst="c" * (6 * MB))


def test_powiekszenie_bazy_ponad_limit_dalej_odrzucane(firma_po_obnizeniu):
    with pytest.raises(ValidationError):
        sprawdz_limit_bazy_wiedzy(firma_po_obnizeniu, "n" * (1 * MB))


def test_zamiana_na_wieksza_tresc_odrzucana(firma_po_obnizeniu):
    # Zastąpienie 1 MB przez 2 MB to wzrost bazy - nieważne, że przez zamianę.
    with pytest.raises(ValidationError):
        sprawdz_limit_bazy_wiedzy(
            firma_po_obnizeniu, "n" * (2 * MB), zastepowany_tekst="r" * (1 * MB)
        )


def test_komunikat_mowi_o_przekroczonym_limicie_a_nie_o_przyszlym(firma_po_obnizeniu):
    # „Baza przekroczyłaby limit" jest myląca, gdy już go przekracza: klient
    # szuka, co takiego dodaje, zamiast dowiedzieć się, że jest ponad planem.
    with pytest.raises(ValidationError) as odmowa:
        sprawdz_limit_bazy_wiedzy(firma_po_obnizeniu, "n" * 100)

    tresc = str(odmowa.value)
    assert "przekracza limit" in tresc
    assert "8.0 MB" in tresc and "5 MB" in tresc


class TestBezObnizeniaPlanu:
    """Firma mieszcząca się w limicie ma działać dokładnie jak dotąd."""

    def test_dodanie_w_ramach_limitu_przechodzi(self, tenant, subscribtion):
        Document.objects.create(tenant=tenant, name="Cennik", content="c" * MB)

        sprawdz_limit_bazy_wiedzy(tenant, "n" * MB)

    def test_dodanie_ponad_limit_odrzucane(self, tenant, subscribtion):
        Document.objects.create(tenant=tenant, name="Cennik", content="c" * (4 * MB))

        with pytest.raises(ValidationError) as odmowa:
            sprawdz_limit_bazy_wiedzy(tenant, "n" * (2 * MB))

        assert "przekroczyłaby limit" in str(odmowa.value)

    def test_granica_dokladnie_na_limicie_przechodzi(self, tenant, subscribtion):
        # Równo tyle, ile wolno: limit to „nie więcej niż", nie „mniej niż".
        sprawdz_limit_bazy_wiedzy(tenant, "n" * (5 * MB))
