"""
Limit wielkości bazy wiedzy.

Poprzednia wersja nie działała z dwóch niezależnych powodów naraz. Miała własny
słownik planów ("free"/"pro"/"enterprise") niepodpięty do katalogu, więc po
zmianie cennika płacący klient dostawał limit darmowego. I — poważniej —
siedziała w `DocumentSerializer.validate()`, podczas gdy oba widoki używające
tego serializera są tylko do odczytu, a upload tworzy dokument bezpośrednio.
Metoda nie wykonywała się nigdy.

Stąd nacisk tych testów: sprawdzają, że limit realnie zatrzymuje zapis na obu
drogach dodawania wiedzy, a nie że funkcja zwraca poprawną liczbę.
"""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from documents.models import Document
from documents.utils.tresc_strony import TrescStrony
from documents.validators import (
    MB, limit_bazy_wiedzy_mb, rozmiar_bazy_wiedzy, sprawdz_limit_bazy_wiedzy,
)


@pytest.mark.django_db
class TestLimituZKatalogu:
    @pytest.mark.parametrize("plan,limit_mb", [
        ("start", 5), ("grow", 25), ("pro", 100),
    ])
    def test_limit_pochodzi_z_cennika(self, tenant, subscribtion, plan, limit_mb):
        subscribtion.plan_type = plan
        subscribtion.save()

        assert limit_bazy_wiedzy_mb(tenant) == limit_mb

    def test_platny_plan_nie_dostaje_limitu_darmowego(self, tenant, subscribtion):
        """
        Sedno pierwszej usterki: "grow" nie istniał w starym słowniku planów
        i wpadał w wartość domyślną przewidzianą dla planu darmowego.
        """
        subscribtion.plan_type = "grow"
        subscribtion.save()

        assert limit_bazy_wiedzy_mb(tenant) == 25

    def test_plan_spoza_katalogu_dostaje_najnizszy_limit(self, tenant, subscribtion):
        subscribtion.plan_type = "Prymium"
        subscribtion.save()

        assert limit_bazy_wiedzy_mb(tenant) == 5


@pytest.mark.django_db
class TestPomiaruRozmiaru:
    def test_pusta_baza_to_zero(self, tenant):
        assert rozmiar_bazy_wiedzy(tenant) == 0

    def test_sumuje_tresc_wszystkich_dokumentow(self, tenant):
        Document.objects.create(tenant=tenant, name="a", content="x" * 100)
        Document.objects.create(tenant=tenant, name="b", content="y" * 250)

        assert rozmiar_bazy_wiedzy(tenant) == 350

    def test_nie_liczy_cudzych_dokumentow(self, tenant):
        """Limit należy do firmy — dokumenty innej nie mogą go zjadać."""
        from api.tests.factories import TenantFactory

        obcy = TenantFactory()
        Document.objects.create(tenant=obcy, name="cudzy", content="z" * 5000)
        Document.objects.create(tenant=tenant, name="moj", content="x" * 10)

        assert rozmiar_bazy_wiedzy(tenant) == 10


@pytest.mark.django_db
class TestSprawdzaniaLimitu:
    def test_mieszczaca_sie_tresc_przechodzi(self, tenant, subscribtion):
        subscribtion.plan_type = "start"
        subscribtion.save()

        sprawdz_limit_bazy_wiedzy(tenant, "x" * 1000)

    def test_przekroczenie_zatrzymuje(self, tenant, subscribtion):
        subscribtion.plan_type = "start"
        subscribtion.save()

        with pytest.raises(ValidationError):
            sprawdz_limit_bazy_wiedzy(tenant, "x" * (6 * MB))

    def test_liczy_sie_suma_z_tym_co_juz_jest(self, tenant, subscribtion):
        """
        Pojedynczy dokument mieści się w limicie, ale nie razem z istniejącymi —
        bez tego dałoby się przekroczyć limit dowolnie, wgrywając po kawałku.
        """
        subscribtion.plan_type = "start"
        subscribtion.save()
        Document.objects.create(tenant=tenant, name="duzy", content="x" * (4 * MB))

        with pytest.raises(ValidationError):
            sprawdz_limit_bazy_wiedzy(tenant, "y" * (2 * MB))

    def test_wyzszy_plan_przepuszcza_to_samo(self, tenant, subscribtion):
        subscribtion.plan_type = "pro"
        subscribtion.save()
        Document.objects.create(tenant=tenant, name="duzy", content="x" * (4 * MB))

        sprawdz_limit_bazy_wiedzy(tenant, "y" * (2 * MB))

    def test_komunikat_mowi_co_zrobic(self, tenant, subscribtion):
        subscribtion.plan_type = "start"
        subscribtion.save()

        with pytest.raises(ValidationError) as blad:
            sprawdz_limit_bazy_wiedzy(tenant, "x" * (6 * MB))

        tresc = str(blad.value)
        assert "5 MB" in tresc
        assert "wyższy plan" in tresc


@pytest.mark.django_db
class TestEgzekwowaniaPrzyUploadzie:
    """
    Najważniejsza część. Poprzedni walidator był poprawny w środku, ale nikt
    go nie wołał — testy sprawdzające samą funkcję przechodziły, a limit
    w produkcie nie istniał.
    """
    URL = "/api/documents-upload/"

    def zaloguj(self, user, tenant, plan="start"):
        user.tenant = tenant
        user.role = "owner"
        user.save()
        subskrypcja = tenant.subscription
        subskrypcja.plan_type = plan
        subskrypcja.save()

        klient = APIClient()
        klient.force_authenticate(user=user)
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
        return klient

    def test_upload_ponad_limit_jest_odrzucany(self, user, tenant, subscribtion, mocker):
        mocker.patch(
            "api.views.documents.extract_text_from_pdf",
            return_value="x" * (6 * MB),
        )
        klient = self.zaloguj(user, tenant, "start")

        response = klient.post(
            self.URL,
            {"file": SimpleUploadedFile("duzy.pdf", b"%PDF-1.4", content_type="application/pdf")},
            format="multipart",
        )

        assert response.status_code == 400
        assert not Document.objects.filter(tenant=tenant).exists()

    def test_upload_w_limicie_przechodzi(self, user, tenant, subscribtion, mocker):
        mocker.patch(
            "api.views.documents.extract_text_from_pdf", return_value="treść firmy",
        )
        mocker.patch("api.views.documents.enqueue")
        klient = self.zaloguj(user, tenant, "start")

        response = klient.post(
            self.URL,
            {"file": SimpleUploadedFile("maly.pdf", b"%PDF-1.4", content_type="application/pdf")},
            format="multipart",
        )

        assert response.status_code == 201
        assert Document.objects.filter(tenant=tenant).count() == 1

    def test_odrzucony_dokument_nie_zostawia_sladu(self, user, tenant, subscribtion, mocker):
        """
        Sprawdzamy przed zapisem, nie po. Dokument zapisany i zaraz usunięty
        zostawiłby plik w magazynie i zadanie embeddingów w kolejce.
        """
        mocker.patch(
            "api.views.documents.extract_text_from_pdf",
            return_value="x" * (6 * MB),
        )
        kolejka = mocker.patch("api.views.documents.enqueue")
        klient = self.zaloguj(user, tenant, "start")

        klient.post(
            self.URL,
            {"file": SimpleUploadedFile("duzy.pdf", b"%PDF-1.4", content_type="application/pdf")},
            format="multipart",
        )

        kolejka.assert_not_called()


@pytest.mark.django_db
class TestEgzekwowaniaPrzyImporcieStrony:
    def test_import_strony_tez_podlega_limitowi(self, tenant, subscribtion, mocker):
        """
        Bez tego limit dałoby się obejść, dodając stronę zamiast dokumentu —
        a crawler potrafi zaciągnąć dziesiątki podstron naraz.
        """
        from documents.website_import import import_website_as_document

        subscribtion.plan_type = "start"
        subscribtion.save()
        mocker.patch(
            "documents.website_import.fetch_text_from_url",
            return_value=TrescStrony("x" * (6 * MB), 6 * MB),
        )

        with pytest.raises(ValidationError):
            import_website_as_document(tenant, "https://przyklad.pl")

        assert not Document.objects.filter(tenant=tenant).exists()
