"""
Odmowy bez rozpoznanej firmy zliczane w jednym wierszu na powód i dzień (2.32.15).

Unikalność (firma, powód, dzień) nie obejmowała wierszy bez firmy - w
PostgreSQL dwa NULL-e nie są sobie równe. Dwa równoległe pierwsze żądania ze
złym kluczem zakładały więc dwa wiersze, a każde następne podbijało oba:
licznik „zły klucz" rósł podwójnie (audyt 2026-10, P17). Teraz ograniczenie
traktuje NULL jak wartość, a migracja scala duplikaty, które już są.
"""

from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from accounts.odmowy import PowodOdmowy, ZliczenieOdmow, zapisz_odmowe

PRZED = [("accounts", "0047_powody_odmow_pojemnosci")]


def wiersz(model, **pola):
    teraz = timezone.now()
    dane = {"powod": PowodOdmowy.ZLY_KLUCZ, "dzien": timezone.localdate(teraz), "liczba": 1}
    dane.update(pola)
    dane.setdefault("pierwsza", teraz)
    dane.setdefault("ostatnia", teraz)
    return model.objects.create(tenant=None, **dane)


@pytest.mark.django_db
def test_drugi_wiersz_bez_firmy_tego_dnia_jest_odrzucany():
    wiersz(ZliczenieOdmow)

    with pytest.raises(IntegrityError), transaction.atomic():
        wiersz(ZliczenieOdmow)


@pytest.mark.django_db
def test_zapis_odmowy_bez_firmy_podbija_jeden_wiersz():
    for _ in range(3):
        zapisz_odmowe(None, PowodOdmowy.ZLY_KLUCZ)

    zliczenie = ZliczenieOdmow.objects.get(tenant=None)
    assert zliczenie.liczba == 3


@pytest.mark.django_db
def test_wyscig_przy_pierwszej_odmowie_dnia_konczy_sie_jednym_wierszem(monkeypatch):
    """Drugi zapis trafia na lukę między UPDATE a INSERT - jak przy wyścigu."""
    wiersz(ZliczenieOdmow)
    pierwszy_update = {"zrobiony": False}
    oryginal = ZliczenieOdmow.objects.filter(tenant=None).__class__.update

    def update_jakby_wiersza_nie_bylo(queryset, **pola):
        if not pierwszy_update["zrobiony"]:
            pierwszy_update["zrobiony"] = True
            return 0
        return oryginal(queryset, **pola)

    monkeypatch.setattr(type(ZliczenieOdmow.objects.all()), "update", update_jakby_wiersza_nie_bylo)

    with transaction.atomic():
        zapisz_odmowe(None, PowodOdmowy.ZLY_KLUCZ)

    assert ZliczenieOdmow.objects.filter(tenant=None).count() == 1
    assert ZliczenieOdmow.objects.get(tenant=None).liczba == 2


@pytest.mark.django_db(transaction=True)
def test_migracja_scala_istniejace_duplikaty():
    executor = MigrationExecutor(connection)
    najnowsze = executor.loader.graph.leaf_nodes()
    executor.migrate(PRZED)
    stare = executor.loader.project_state(PRZED).apps.get_model("accounts", "ZliczenieOdmow")
    teraz = timezone.now()
    try:
        wiersz(stare, liczba=2, pierwsza=teraz - timedelta(hours=3), ostatnia=teraz)
        wiersz(stare, liczba=5, pierwsza=teraz - timedelta(hours=1), zgloszone=True)
        wiersz(stare, powod=PowodOdmowy.BRAK_KLUCZA, liczba=7)

        MigrationExecutor(connection).migrate(najnowsze)

        zly_klucz = ZliczenieOdmow.objects.get(tenant=None, powod=PowodOdmowy.ZLY_KLUCZ)
        assert zly_klucz.liczba == 7
        assert zly_klucz.pierwsza == teraz - timedelta(hours=3)
        assert zly_klucz.zgloszone is True
        assert ZliczenieOdmow.objects.get(tenant=None, powod=PowodOdmowy.BRAK_KLUCZA).liczba == 7
    finally:
        MigrationExecutor(connection).migrate(najnowsze)
        ZliczenieOdmow.objects.all().delete()
