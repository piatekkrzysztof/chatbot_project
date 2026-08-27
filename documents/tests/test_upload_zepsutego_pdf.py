"""
Wgranie uszkodzonego PDF-a.

Kategoria ryzyka: CICHA AWARIA po stronie użytkownika. Wgrywający dostawał
pięćsetkę - nieodróżnialną od awarii całego serwisu - zamiast informacji, że
to jego plik jest zepsuty. W Sentry lądował przy tym szum zamiast sygnału.

Uszkodzony PDF nie jest przypadkiem brzegowym: urwane pobieranie, plik ze
skanera, dokument zapisany przez program, który się wysypał. Nikt tego nie
rozpozna przed wgraniem.

Ten sam wyjątek łapie od pypdf 6 `LimitReachedError`, czyli przerwaną próbę
przetworzenia pliku zbudowanego tak, żeby zająć cały czas procesora - jedną
z pięćdziesięciu trzech podatności, przez które ta wersja została podniesiona.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from documents.models import Document


@pytest.mark.django_db
class TestUploaduZepsutegoPliku:
    URL = "/api/documents-upload/"

    def zaloguj(self, user, tenant):
        # Rola i plan ustawiane jawnie: domyslna fikstura daje uzytkownika
        # o roli `viewer`, ktory nie ma prawa wgrywac - bez tego test odbijal
        # sie o 403 i przechodzil z niewlasciwego powodu (bo 403 rowniez nie
        # tworzy dokumentu).
        user.role = "owner"
        user.save()
        subskrypcja = tenant.subscription
        subskrypcja.plan_type = "start"
        subskrypcja.save()

        klient = APIClient()
        klient.force_authenticate(user=user)
        klient.credentials(HTTP_X_API_KEY=str(tenant.api_key))
        return klient

    def test_uszkodzony_pdf_daje_czytelna_odmowe_a_nie_piecsetke(self, user, tenant, subscribtion):
        klient = self.zaloguj(user, tenant)

        odpowiedz = klient.post(
            self.URL,
            {
                "file": SimpleUploadedFile(
                    "urwany.pdf",
                    b"%PDF-1.4\n1 0 obj",  # nagłówek jest, reszty brak
                    content_type="application/pdf",
                )
            },
            format="multipart",
        )

        assert odpowiedz.status_code == 400
        assert "PDF" in odpowiedz.data["error"]

    def test_nieudany_odczyt_nie_zostawia_dokumentu(self, user, tenant, subscribtion):
        # Dokument zapisany mimo nieudanego odczytu byłby pusty, wyglądałby
        # w panelu na poprawny i zająłby miejsce w limicie bazy wiedzy.
        klient = self.zaloguj(user, tenant)

        klient.post(
            self.URL,
            {
                "file": SimpleUploadedFile(
                    "urwany.pdf", b"%PDF-1.4\n1 0 obj", content_type="application/pdf"
                )
            },
            format="multipart",
        )

        assert not Document.objects.filter(tenant=tenant).exists()

    def test_plik_ktory_udaje_pdf_rozszerzeniem(self, user, tenant, subscribtion):
        # Rozszerzenie decyduje o tym, czy w ogóle próbujemy czytać - więc
        # zwykły tekst nazwany .pdf trafia do parsera i musi odbić się tak samo.
        klient = self.zaloguj(user, tenant)

        odpowiedz = klient.post(
            self.URL,
            {
                "file": SimpleUploadedFile(
                    "podszywacz.pdf",
                    b"to jest zwykly tekst, nie PDF",
                    content_type="application/pdf",
                )
            },
            format="multipart",
        )

        assert odpowiedz.status_code == 400
