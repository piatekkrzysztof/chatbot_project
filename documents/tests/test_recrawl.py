"""
Częstotliwość odświeżania treści ze stron klienta.

Cennik obiecuje odświeżanie ręczne (Start), tygodniowe (Grow) i dzienne (Pro),
ale zadanie cykliczne pobierało wszystkie aktywne źródła przy każdym przebiegu,
niezależnie od planu. Różnica jest realna, nie tylko cennikowa: każdy przebieg
to ruch na stronie klienta i przeliczenie embeddingów, za które płacimy.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.plans import recrawl_days_for
from documents.models import WebsiteSource
from documents.tasks import crawl_all_active_sources


@pytest.fixture
def zrodlo(tenant):
    return WebsiteSource.objects.create(
        tenant=tenant, name="Strona", url="https://przyklad.pl", is_active=True
    )


class TestCzestotliwosciWKatalogu:
    @pytest.mark.parametrize(
        "plan,dni",
        [
            ("start", None),
            ("grow", 7),
            ("pro", 1),
        ],
    )
    def test_czestotliwosc_pochodzi_z_planu(self, plan, dni):
        assert recrawl_days_for(plan) == dni

    def test_nieznany_plan_nie_odswieza_sam(self):
        """
        Automatyczne pobieranie kosztuje nas ruch i embeddingi, więc przy
        niepewności nie robimy tego z własnej inicjatywy.
        """
        assert recrawl_days_for("Prymium") is None
        assert recrawl_days_for(None) is None


@pytest.mark.django_db
class TestZadaniaCyklicznego:
    def test_start_nie_jest_odswiezany_automatycznie(self, tenant, subscribtion, zrodlo, mocker):
        """Sedno: plan Start ma w cenniku odświeżanie wyłącznie ręczne."""
        subscribtion.plan_type = "start"
        subscribtion.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        crawl_all_active_sources()

        kolejka.assert_not_called()

    def test_pierwsze_pobranie_dziala_od_razu(self, tenant, subscribtion, zrodlo, mocker):
        """Świeżo dodane źródło nie ma daty pobrania — nie ma na co czekać."""
        subscribtion.plan_type = "grow"
        subscribtion.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        crawl_all_active_sources()

        kolejka.assert_called_once()

    def test_grow_czeka_tydzien(self, tenant, subscribtion, zrodlo, mocker):
        subscribtion.plan_type = "grow"
        subscribtion.save()
        zrodlo.last_crawled_at = timezone.now() - timedelta(days=3)
        zrodlo.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        crawl_all_active_sources()

        kolejka.assert_not_called()

    def test_grow_odswieza_po_tygodniu(self, tenant, subscribtion, zrodlo, mocker):
        subscribtion.plan_type = "grow"
        subscribtion.save()
        zrodlo.last_crawled_at = timezone.now() - timedelta(days=8)
        zrodlo.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        crawl_all_active_sources()

        kolejka.assert_called_once()

    def test_pro_odswieza_codziennie(self, tenant, subscribtion, zrodlo, mocker):
        """Ta sama data, która wstrzymuje plan Grow, przepuszcza plan Pro."""
        subscribtion.plan_type = "pro"
        subscribtion.save()
        zrodlo.last_crawled_at = timezone.now() - timedelta(days=3)
        zrodlo.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        crawl_all_active_sources()

        kolejka.assert_called_once()

    def test_wylaczone_zrodlo_jest_pomijane(self, tenant, subscribtion, zrodlo, mocker):
        subscribtion.plan_type = "pro"
        subscribtion.save()
        zrodlo.is_active = False
        zrodlo.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        crawl_all_active_sources()

        kolejka.assert_not_called()


@pytest.mark.django_db
class TestRecznegoOdswiezania:
    def test_start_moze_odswiezyc_recznie(self, user, tenant, subscribtion, zrodlo, mocker):
        """
        Bez tego plan Start nie miałby żadnego sposobu na uwzględnienie zmian
        na własnej stronie — a cennik obiecuje mu odświeżanie ręczne.
        """
        subscribtion.plan_type = "start"
        subscribtion.save()
        user.tenant = tenant
        user.role = "owner"
        user.save()
        kolejka = mocker.patch("api.views.documents.enqueue")

        klient = APIClient()
        klient.force_authenticate(user=user)
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
        response = klient.post(f"/api/website-sources/{zrodlo.id}/recrawl/")

        assert response.status_code == 202
        kolejka.assert_called_once()

    def test_nie_da_sie_odswiezyc_cudzego_zrodla(self, user, tenant, subscribtion, mocker):
        from api.tests.factories import TenantFactory

        obcy = TenantFactory()
        cudze = WebsiteSource.objects.create(tenant=obcy, name="Cudza", url="https://cudza.pl")
        user.tenant = tenant
        user.role = "owner"
        user.save()
        kolejka = mocker.patch("api.views.documents.enqueue")

        klient = APIClient()
        klient.force_authenticate(user=user)
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
        response = klient.post(f"/api/website-sources/{cudze.id}/recrawl/")

        assert response.status_code == 404
        kolejka.assert_not_called()


@pytest.mark.django_db
class TestOdswiezanieTylkoZWaznymPlanem:
    """
    Plan musi być aktywny i ważny, nie tylko nazywać się Pro (2.32.12).

    Do 2.32.11 zadanie patrzyło wyłącznie na kod planu. Firma, której Pro
    skończyło się miesiące temu, dalej miała źródła pobierane codziennie,
    z przeliczaniem embeddingów przy każdej zmianie treści - na nasz koszt
    i na czas jedynego workera (audyt 2026-10, P14).
    """

    @pytest.mark.parametrize(
        "zmiana",
        [
            {"is_active": False},
            {"end_date": timezone.now().date() - timedelta(days=1)},
            {"start_date": timezone.now().date() + timedelta(days=1)},
        ],
        ids=["nieaktywny", "po-terminie", "przed-startem"],
    )
    def test_niewazny_plan_pro_nie_odswieza(self, tenant, subscribtion, zrodlo, mocker, zmiana):
        subscribtion.plan_type = "pro"
        for pole, wartosc in zmiana.items():
            setattr(subscribtion, pole, wartosc)
        subscribtion.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        assert crawl_all_active_sources() == 0
        kolejka.assert_not_called()

    def test_wazny_plan_pro_odswieza(self, tenant, subscribtion, zrodlo, mocker):
        subscribtion.plan_type = "pro"
        subscribtion.save()
        kolejka = mocker.patch("documents.tasks.enqueue")

        assert crawl_all_active_sources() == 1
        kolejka.assert_called_once()

    def test_ostatni_dzien_planu_jeszcze_odswieza(self, tenant, subscribtion, zrodlo, mocker):
        subscribtion.plan_type = "pro"
        subscribtion.end_date = timezone.now().date()
        subscribtion.save()
        mocker.patch("documents.tasks.enqueue")

        assert crawl_all_active_sources() == 1
