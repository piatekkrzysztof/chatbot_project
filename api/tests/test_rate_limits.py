"""
Limity żądań: stawki z katalogu planów i wspólny licznik.

Dwie usterki, obie ciche. Stawki mieszkały w osobnym słowniku, gdzie plany
nazywały się free/pro/enterprise — po wprowadzeniu cennika "basic" nie pasował
do niczego i klient płacący 99 zł był limitowany dokładnie jak darmowy. A same
liczniki szły do pamięci procesu, więc przy czterech procesach gunicorna realny
limit był czterokrotnie wyższy od deklarowanego.
"""
import pytest
from django.test import override_settings

from accounts.plans import PLANS, rate_for
from api.checks import per_process_rate_limits, trusted_proxy_depth
from api.throttles import APIKeyRateThrottle, SubscriptionRateThrottle


class TestStawkiZKatalogu:
    def test_kazdy_platny_plan_ma_wlasna_stawke(self):
        """Brak wpisu oznaczał po cichu limit darmowy — stąd ten test."""
        stawki = {kod: PLANS[kod].rate_per_minute for kod in PLANS}

        assert all(v > 0 for v in stawki.values()), stawki
        assert len(set(stawki.values())) == len(stawki), (
            f"Dwa plany z tą samą stawką sugerują przeoczenie: {stawki}"
        )

    def test_basic_nie_jest_traktowany_jak_darmowy(self):
        throttle = APIKeyRateThrottle()

        basic = int(throttle.get_plan_rate("basic").split("/")[0])
        nieznany = int(throttle.get_plan_rate("cokolwiek").split("/")[0])

        assert basic > nieznany

    def test_stawki_rosna_wraz_z_planem(self):
        posortowane = sorted(PLANS.values(), key=lambda p: p.price_pln)
        stawki = [p.rate_per_minute for p in posortowane]

        assert stawki == sorted(stawki)

    def test_plan_spoza_katalogu_dostaje_bezpieczna_wartosc(self):
        """Subskrypcje sprzed cennika nie mogą zostać bez limitu ani zablokowane."""
        rate = rate_for("Prymium")

        wartosc = int(rate.split("/")[0])
        assert 0 < wartosc < min(p.rate_per_minute for p in PLANS.values())

    def test_panel_ma_lozniejszy_limit_niz_czat(self):
        """Jedno otwarcie strony panelu to kilka żądań — nie mogą się obijać o limit."""
        czat = int(APIKeyRateThrottle().get_plan_rate("pro").split("/")[0])
        panel = int(SubscriptionRateThrottle().get_plan_rate("pro").split("/")[0])

        assert panel > czat


class TestOstrzezenieOLicznikach:
    def test_brak_wspolnego_cache_daje_ostrzezenie(self, settings):
        settings.DEBUG = False
        settings.USE_SHARED_CACHE = False

        assert [w.id for w in per_process_rate_limits(None)] == ["api.W001"]

    def test_wspolny_cache_milczy(self, settings):
        settings.DEBUG = False
        settings.USE_SHARED_CACHE = True

        assert per_process_rate_limits(None) == []

    def test_lokalnie_nie_zawracamy_glowy(self, settings):
        """Na maszynie dewelopera jest jeden proces — ostrzeżenie byłoby szumem."""
        settings.DEBUG = True
        settings.USE_SHARED_CACHE = False

        assert per_process_rate_limits(None) == []


class TestOstrzezeniaOProxy:
    """
    Zła wartość TRUSTED_PROXY_DEPTH jest groźniejsza niż brak limitu: przy 0
    za proxy wszyscy odwiedzający zlewają się w jeden adres, więc limit na
    odwiedzającego zablokowałby widget wszystkim klientom naraz. Ostrzeżenie
    ma się pojawić w logu wdrożenia, zanim to nastąpi.
    """

    @override_settings(DEBUG=False, TRUSTED_PROXY_DEPTH=0)
    def test_ostrzega_na_produkcji_bez_konfiguracji(self):
        assert [w.id for w in trusted_proxy_depth(None)] == ["api.W002"]

    @override_settings(DEBUG=False, TRUSTED_PROXY_DEPTH=2)
    def test_milczy_gdy_skonfigurowane(self):
        assert trusted_proxy_depth(None) == []

    @override_settings(DEBUG=True, TRUSTED_PROXY_DEPTH=0)
    def test_milczy_lokalnie(self):
        """Lokalnie nie ma proxy, więc 0 jest poprawną wartością."""
        assert trusted_proxy_depth(None) == []
