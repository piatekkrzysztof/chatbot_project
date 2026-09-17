"""
Usuwanie dokumentu z bazy wiedzy.

Kategoria ryzyka: WŁASNE DANE KLIENTA. API dokumentów było tylko do odczytu,
więc dokument wgrany przez pomyłkę zostawał w bazie wiedzy na stałe: zajmował
miejsce w limicie planu i bot dalej z niego odpowiadał. Panel administracyjny
nie jest odpowiedzią - to nasze narzędzie, nie klienta.

Drugi warunek, równie ważny: plik musi zniknąć z magazynu. Django przy
usunięciu rekordu zostawia plik tam, gdzie leżał, więc "usunięty" dokument
dalej zajmowałby miejsce, za które klient płaci, a jego treść byłaby do
odczytania dla każdego, kto ma dostęp do magazynu.

Od 2.8.1 kasuje go sygnał `documents.signals`, po zatwierdzeniu transakcji -
stąd `django_capture_on_commit_callbacks` w teście, który tego pilnuje. Poza
testem zapytanie nie jest owinięte transakcją (`ATOMIC_REQUESTS` wyłączone),
więc plik znika jeszcze w trakcie odpowiedzi. Dlaczego akurat po zatwierdzeniu,
mówi docs/usuwanie-plikow.md.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import CustomUser, Tenant
from documents.models import Document, DocumentChunk
from documents.wymiar import WYMIAR_WEKTORA

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def prywatny_magazyn(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"


def klient(uzytkownik, tenant, rola="owner"):
    uzytkownik.tenant = tenant
    uzytkownik.role = rola
    uzytkownik.save()
    api = APIClient()
    api.force_authenticate(user=uzytkownik)
    api.credentials(HTTP_X_API_KEY=str(tenant.api_key))
    return api


def dokument_z_plikiem(tenant, nazwa="cennik.txt"):
    dokument = Document.objects.create(
        tenant=tenant, name=nazwa, file=SimpleUploadedFile(nazwa, b"CENNIK"), processed=True
    )
    DocumentChunk.objects.create(
        document=dokument, content="fragment", embedding=[0.0] * WYMIAR_WEKTORA
    )
    return dokument


def test_wlasciciel_usuwa_dokument_razem_z_fragmentami_i_plikiem(
    user, tenant, subscribtion, django_capture_on_commit_callbacks
):
    dokument = dokument_z_plikiem(tenant)
    magazyn, nazwa_pliku = dokument.file.storage, dokument.file.name
    assert magazyn.exists(nazwa_pliku)

    with django_capture_on_commit_callbacks(execute=True):
        odpowiedz = klient(user, tenant).delete(reverse("documents-detail", args=[dokument.pk]))

    assert odpowiedz.status_code == 204
    assert not Document.objects.filter(pk=dokument.pk).exists()
    assert not DocumentChunk.objects.filter(document_id=dokument.pk).exists()
    assert not magazyn.exists(nazwa_pliku), "plik został w magazynie, mimo usunięcia dokumentu"


def test_pracownik_tez_usuwa(user, tenant, subscribtion):
    # Kto może wgrać, ten może naprawić własną pomyłkę.
    dokument = dokument_z_plikiem(tenant)

    odpowiedz = klient(user, tenant, "employee").delete(
        reverse("documents-detail", args=[dokument.pk])
    )

    assert odpowiedz.status_code == 204
    assert not Document.objects.filter(pk=dokument.pk).exists()


def test_viewer_nie_usuwa(user, tenant, subscribtion):
    dokument = dokument_z_plikiem(tenant)

    odpowiedz = klient(user, tenant, "viewer").delete(
        reverse("documents-detail", args=[dokument.pk])
    )

    assert odpowiedz.status_code == 403
    assert Document.objects.filter(pk=dokument.pk).exists()


def test_dokumentu_innej_firmy_nie_da_sie_usunac(user, tenant, subscribtion):
    obca = Tenant.objects.create(name="Obca firma", owner_email="szef@obca.pl")
    cudzy = dokument_z_plikiem(obca, "cudzy.txt")

    odpowiedz = klient(user, tenant).delete(reverse("documents-detail", args=[cudzy.pk]))

    assert odpowiedz.status_code == 404
    assert Document.objects.filter(pk=cudzy.pk).exists()


def test_brak_pliku_w_magazynie_nie_zatrzymuje_usuniecia(
    user, tenant, subscribtion, django_capture_on_commit_callbacks
):
    # Plik mógł zniknąć wcześniej: nieudane wdrożenie, ręczne porządki
    # w magazynie, przeniesienie między magazynami. Wpis w bazie musi dać się
    # usunąć mimo to, inaczej klient zostaje z dokumentem nie do ruszenia.
    dokument = dokument_z_plikiem(tenant)
    dokument.file.storage.delete(dokument.file.name)

    with django_capture_on_commit_callbacks(execute=True):
        odpowiedz = klient(user, tenant).delete(reverse("documents-detail", args=[dokument.pk]))

    assert odpowiedz.status_code == 204
    assert not Document.objects.filter(pk=dokument.pk).exists()


def test_dokument_z_importu_strony_tez_da_sie_usunac(user, tenant, subscribtion):
    ze_strony = Document.objects.create(
        tenant=tenant, name="Strona firmy", content="treść", source_url="https://firma.pl/oferta"
    )

    odpowiedz = klient(user, tenant).delete(reverse("documents-detail", args=[ze_strony.pk]))

    assert odpowiedz.status_code == 204
    assert not Document.objects.filter(pk=ze_strony.pk).exists()


def test_usuniecie_zostawia_slad_w_dzienniku(user, tenant, subscribtion):
    from accounts.models import WpisDziennika

    dokument = dokument_z_plikiem(tenant)

    klient(user, tenant).delete(reverse("documents-detail", args=[dokument.pk]))

    wpis = WpisDziennika.objects.get(sciezka=f"/api/documents/{dokument.pk}/")
    assert (wpis.metoda, wpis.status, wpis.tenant) == ("DELETE", 204, tenant)
