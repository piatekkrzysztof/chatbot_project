"""
Plik znika razem z wierszem, do którego należał - każdą drogą, nie jedną.

Kategoria ryzyka: DANE, KTÓRE MIAŁY ZNIKNĄĆ. Usunięcie pliku z magazynu było
dopisane w jednym miejscu: w widoku panelu (2.8.0). Każda inna droga - panel
administracyjny, usunięcie firmy, usunięcie hurtem z powłoki, żądanie klienta
o skasowanie danych - kasowała wiersz w bazie, a plik zostawiała w prywatnym
magazynie. Bez wiersza nikt go już nie znajdzie i nikt go nie skasuje, więc
treść, którą klient kazał usunąć, leży tam bezterminowo.

Dlatego kasowanie pliku jest tutaj przypięte do usunięcia wiersza (sygnał),
a nie do przycisku w panelu. Te testy pilnują wszystkich dróg naraz i tego,
co ma się NIE stać: wycofana transakcja nie może zabrać pliku, bo kopii nie
trzymamy, a wiersz po wycofaniu zostaje.
"""

import json

import pytest
from django.core import serializers
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction

from accounts.models import Tenant
from documents.models import Document, DocumentChunk
from documents.wymiar import WYMIAR_WEKTORA


@pytest.fixture(autouse=True)
def magazyn_w_katalogu_testu(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "public"
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"


def dokument(tenant, tresc=b"TAJNA TRESC", nazwa="cennik.txt"):
    return Document.objects.create(tenant=tenant, name=nazwa, file=SimpleUploadedFile(nazwa, tresc))


def jest_w_magazynie(nazwa):
    return storages["private_documents"].exists(nazwa)


@pytest.mark.django_db
def test_usuniecie_dokumentu_zabiera_plik_z_magazynu(tenant, django_capture_on_commit_callbacks):
    doc = dokument(tenant)
    nazwa = doc.file.name
    assert jest_w_magazynie(nazwa)

    with django_capture_on_commit_callbacks(execute=True):
        doc.delete()

    assert not jest_w_magazynie(nazwa)


@pytest.mark.django_db
def test_usuniecie_firmy_zabiera_pliki_jej_dokumentow(tenant, django_capture_on_commit_callbacks):
    # Usunięcie firmy to jedyna droga, którą klient realizuje prawo do bycia
    # zapomnianym. Kaskada bazy zabiera wiersze dokumentów, ale magazyn plików
    # nie jest częścią bazy i o kaskadzie nic nie wie.
    nazwy = [dokument(tenant, nazwa=f"plik{i}.txt").file.name for i in range(3)]

    with django_capture_on_commit_callbacks(execute=True):
        tenant.delete()

    assert [nazwa for nazwa in nazwy if jest_w_magazynie(nazwa)] == []


@pytest.mark.django_db
def test_usuniecie_hurtem_zabiera_pliki(tenant, django_capture_on_commit_callbacks):
    # `queryset.delete()` nie woła `Model.delete()` dla żadnego wiersza, więc
    # nadpisanie metody modelu nic by tu nie dało - sygnał daje.
    nazwy = [dokument(tenant, nazwa=f"plik{i}.txt").file.name for i in range(2)]

    with django_capture_on_commit_callbacks(execute=True):
        Document.objects.filter(tenant=tenant).delete()

    assert [nazwa for nazwa in nazwy if jest_w_magazynie(nazwa)] == []


@pytest.mark.django_db(transaction=True)
def test_wycofana_transakcja_zostawia_plik(tenant):
    # Magazyn plików nie bierze udziału w transakcji bazy. Gdyby plik ginął
    # w chwili usunięcia wiersza, wycofanie przywróciłoby wiersz wskazujący
    # na plik, którego już nie ma - i nie byłoby z czego go odtworzyć.
    doc = dokument(tenant)
    nazwa, klucz = doc.file.name, doc.pk

    class Wycofaj(Exception):
        pass

    with pytest.raises(Wycofaj):
        with transaction.atomic():
            doc.delete()
            raise Wycofaj

    # `delete()` czyści `pk` obiektu w pamięci także wtedy, gdy transakcja
    # zostanie wycofana - stąd klucz zapamiętany wcześniej.
    assert Document.objects.filter(pk=klucz).exists()
    assert jest_w_magazynie(nazwa)


@pytest.mark.django_db
def test_dokument_bez_pliku_usuwa_sie_bez_sladu_w_logu(
    tenant, django_capture_on_commit_callbacks, caplog
):
    # Podstrony pobrane z witryny klienta mają treść, ale nie mają pliku.
    # Jest ich najwięcej (do 20 na źródło), więc próba skasowania nieistniejącego
    # pliku zalewałaby log błędami magazynu przy każdym odświeżeniu witryny -
    # i utopiłaby w nich te wpisy, które naprawdę coś znaczą.
    strona = Document.objects.create(
        tenant=tenant, name="Cennik", content="Strzyżenie 50 zł", source="website"
    )
    klucz = strona.pk

    with django_capture_on_commit_callbacks(execute=True):
        strona.delete()

    assert not Document.objects.filter(pk=klucz).exists()
    assert caplog.text == ""


@pytest.mark.django_db
def test_blad_magazynu_nie_cofa_usuniecia(
    tenant, mocker, django_capture_on_commit_callbacks, caplog
):
    # Magazyn jest po sieci i bywa niedostępny. Wiersz jest już wtedy usunięty
    # i cofnąć się go nie da, więc niedostępny magazyn nie może zamienić się
    # w błąd 500 dla kogoś, kto skasował dokument. Nazwa idzie do logu, żeby
    # dało się plik odnaleźć później.
    doc = dokument(tenant)
    nazwa, klucz = doc.file.name, doc.pk
    mocker.patch.object(
        storages["private_documents"], "delete", side_effect=OSError("magazyn nie odpowiada")
    )

    with django_capture_on_commit_callbacks(execute=True):
        doc.delete()

    assert not Document.objects.filter(pk=klucz).exists()
    assert nazwa in caplog.text


@pytest.mark.django_db
def test_fragmenty_znikaja_razem_z_dokumentem(tenant):
    # Kontrola pozytywna dla pochodnych trzymanych w bazie: gdyby kaskada
    # przestała działać, fragmenty bez dokumentu dalej wychodziłyby
    # w wyszukiwaniu, bo filtr firmy stoi na złączonej tabeli dokumentów.
    doc = dokument(tenant)
    klucz = doc.pk
    DocumentChunk.objects.create(
        document=doc, content="Strzyżenie 50 zł", embedding=[0.1] * WYMIAR_WEKTORA
    )

    doc.delete()

    assert not DocumentChunk.objects.filter(document_id=klucz).exists()


@pytest.mark.django_db
def test_usuniecie_firmy_zabiera_logo_i_awatar(django_capture_on_commit_callbacks):
    firma = Tenant.objects.create(name="Rowerownia")
    firma.widget_logo = ContentFile(b"LOGO", name="logo.png")
    firma.widget_avatar = ContentFile(b"AWATAR", name="awatar.png")
    firma.save()
    nazwy = [firma.widget_logo.name, firma.widget_avatar.name]
    assert all(storages["default"].exists(nazwa) for nazwa in nazwy)

    with django_capture_on_commit_callbacks(execute=True):
        firma.delete()

    assert [nazwa for nazwa in nazwy if storages["default"].exists(nazwa)] == []


@pytest.mark.django_db
def test_wymiana_logo_kasuje_poprzednie(django_capture_on_commit_callbacks):
    # Każde wgranie logo zapisuje plik pod nową nazwą, a poprzedni przestaje
    # być z czymkolwiek powiązany. Klient poprawiający logo pięć razy zostawiał
    # pięć plików, z których cztery były już nie do odnalezienia.
    firma = Tenant.objects.create(name="Rowerownia")
    firma.widget_logo = ContentFile(b"STARE", name="stare.png")
    firma.save()
    stare = firma.widget_logo.name

    with django_capture_on_commit_callbacks(execute=True):
        firma.widget_logo = ContentFile(b"NOWE", name="nowe.png")
        firma.save(update_fields=["widget_logo"])

    assert not storages["default"].exists(stare)
    assert storages["default"].exists(firma.widget_logo.name)


@pytest.mark.django_db
def test_zapis_bez_zmiany_logo_nie_rusza_pliku(django_capture_on_commit_callbacks):
    # Zwykły zapis ustawień firmy nie ma prawa skasować logo. Bez tego
    # porównania każde `save()` bez `update_fields` kasowałoby własny plik.
    firma = Tenant.objects.create(name="Rowerownia")
    firma.widget_logo = ContentFile(b"LOGO", name="logo.png")
    firma.save()
    nazwa = firma.widget_logo.name

    with django_capture_on_commit_callbacks(execute=True):
        firma.name = "Rowerownia i Syn"
        firma.save()

    assert storages["default"].exists(nazwa)


@pytest.mark.django_db
def test_odtwarzanie_kopii_nie_kasuje_plikow(tmp_path, django_capture_on_commit_callbacks):
    # Odtwarzanie kopii wgrywa pliki obok bazy, a nazwy w bazie są wtedy
    # nazwami plików, które właśnie przywracamy. Gdyby wczytanie wiersza
    # liczyło się jak wymiana obrazu, odtwarzanie kasowałoby to, co odtwarza.
    firma = Tenant.objects.create(name="Rowerownia")
    firma.widget_logo = ContentFile(b"LOGO", name="logo.png")
    firma.save()
    nazwa = firma.widget_logo.name
    kopia = tmp_path / "kopia.json"
    dane = json.loads(serializers.serialize("json", [firma]))
    dane[0]["fields"]["widget_logo"] = "widget_branding/z-kopii.png"
    kopia.write_text(json.dumps(dane), encoding="utf-8")

    with django_capture_on_commit_callbacks(execute=True):
        call_command("loaddata", str(kopia), verbosity=0)

    assert storages["default"].exists(nazwa)


@pytest.mark.django_db
def test_zapis_bez_obrazow_nie_dopytuje_bazy(django_assert_num_queries):
    # Porównanie z poprzednią wersją kosztuje zapytanie, więc pytamy tylko
    # wtedy, gdy zapis w ogóle dotyczy logo albo awatara. Firma zapisuje się
    # przy każdej zmianie ustawień widgetu i przy każdym zapisie planu.
    with django_assert_num_queries(1):
        firma = Tenant.objects.create(name="Rowerownia")

    firma.name = "Rowerownia i Syn"
    with django_assert_num_queries(1):
        firma.save(update_fields=["name"])
