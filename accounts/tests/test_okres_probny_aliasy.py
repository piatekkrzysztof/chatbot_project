"""
Okres próbny brany po raz drugi na tę samą skrzynkę.

Kategoria ryzyka: DARMOWE PIENIĄDZE. Potwierdzenie adresu daje 14 dni i 2000
wiadomości, czyli 6-10 zł kosztu modelu po naszej stronie. Adres to jednak nie
skrzynka: `jan+sklep@gmail.com`, `jan+bot@gmail.com` i `j.a.n@gmail.com` to
jedno pudełko i jeden człowiek, a dla systemu trzy konta i trzy okresy próbne.
Nic tego nie zauważało.

Zgłaszamy, nie odmawiamy (decyzja właściciela z 29.09.2026), więc testy
pilnują obu stron naraz: że zgłoszenie idzie, **i** że okres próbny mimo to
zostaje przyznany. Wersja, która by go odbierała, przechodziłaby połowę
z nich - stąd asercje na subskrypcję w testach o alarmie.
"""

import pytest
from django.core import mail
from django.db import transaction

from accounts.adresy import normalizuj, skrot_skrzynki
from accounts.models import Subscription, Tenant
from api.views.accounts import zalozenie_okresu_probnego

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def adres_alertow(settings):
    settings.EMAIL_ALERTOW = "alerty@example.com"


def firma(email, nazwa="Firma"):
    return Tenant.objects.create(name=nazwa, owner_email=email)


def probny(tenant, django_capture_on_commit_callbacks):
    """Okres próbny razem z wykonaniem zadań zaplanowanych na zatwierdzenie."""
    with django_capture_on_commit_callbacks(execute=True):
        return zalozenie_okresu_probnego(tenant)


# --- sprowadzanie adresu do skrzynki ----------------------------------------


@pytest.mark.parametrize(
    "adres, oczekiwany",
    [
        ("jan@gmail.com", "jan@gmail.com"),
        ("JAN@Gmail.COM", "jan@gmail.com"),
        ("  jan@gmail.com  ", "jan@gmail.com"),
        # Znacznik po "+" obcinamy u każdego dostawcy: używa go świadomie
        # właściciel skrzynki, nikt inny.
        ("jan+sklep@gmail.com", "jan@gmail.com"),
        ("jan+sklep@firma.pl", "jan@firma.pl"),
        ("jan+a+b@firma.pl", "jan@firma.pl"),
        # Kropki tylko w Gmailu - gdzie indziej to dwie różne skrzynki.
        ("j.a.n@gmail.com", "jan@gmail.com"),
        ("j.a.n@firma.pl", "j.a.n@firma.pl"),
        ("jan@googlemail.com", "jan@gmail.com"),
        # Nie adres albo nic, co da się porównać.
        ("", ""),
        ("jan", ""),
        ("@gmail.com", ""),
        ("jan@", ""),
        ("+tag@gmail.com", ""),
    ],
)
def test_adres_sprowadza_sie_do_skrzynki(adres, oczekiwany):
    assert normalizuj(adres) == oczekiwany


def test_kropki_poza_gmailem_rozrozniaja_dwie_osoby():
    """
    `j.kowalski@` i `jkowalski@` w firmowej domenie to zwykle dwie osoby.

    To jest ta granica, o którą chodzi: sklejenie ich zapaliłoby alarm na
    dwóch obcych ludzi, a alarm zapalany bez powodu przestaje być czytany.
    """
    assert normalizuj("j.kowalski@firma.pl") != normalizuj("jkowalski@firma.pl")


def test_skrot_jest_ten_sam_dla_aliasow_tej_samej_skrzynki():
    assert skrot_skrzynki("jan+sklep@gmail.com") == skrot_skrzynki("j.a.n@gmail.com")


def test_skrot_rozni_sie_dla_roznych_skrzynek():
    assert skrot_skrzynki("jan@gmail.com") != skrot_skrzynki("anna@gmail.com")


def test_skrot_nie_zawiera_adresu():
    """Zapisujemy skrót, nie adres - inaczej byłaby to druga kopia danych osobowych."""
    skrot = skrot_skrzynki("jan@gmail.com")

    assert skrot and "jan" not in skrot and "@" not in skrot


def test_skrot_pusty_gdy_nie_ma_czego_porownac():
    assert skrot_skrzynki("nieadres") == ""


# --- rozpoznanie powtórki ----------------------------------------------------


def test_pierwszy_okres_probny_zapisuje_skrot_i_nie_alarmuje(django_capture_on_commit_callbacks):
    tenant = firma("jan@gmail.com")

    probny(tenant, django_capture_on_commit_callbacks)

    tenant.refresh_from_db()
    assert tenant.skrot_skrzynki == skrot_skrzynki("jan@gmail.com")
    assert mail.outbox == []


def test_drugi_okres_probny_z_aliasu_zglasza_sie(django_capture_on_commit_callbacks):
    """
    Ten test padał na kodzie sprzed zmiany: nic nie łączyło tych dwóch kont.

    Alias różni się znacznikiem i kropkami, więc dla bazy to obcy adres,
    a poczta z obu trafia do jednego pudełka.
    """
    pierwsza = firma("jan@gmail.com", "Pierwsza")
    probny(pierwsza, django_capture_on_commit_callbacks)
    druga = firma("j.a.n+bot@googlemail.com", "Druga")

    subskrypcja = probny(druga, django_capture_on_commit_callbacks)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["alerty@example.com"]
    assert str(pierwsza.pk) in mail.outbox[0].body
    # Zgłoszenie, nie blokada: okres próbny ma zostać przyznany.
    assert subskrypcja.pk is not None
    assert Subscription.objects.filter(tenant=druga).exists()


def test_zgloszenie_nie_zawiera_adresu_email(django_capture_on_commit_callbacks):
    """Alarm to kolejne miejsce, w którym dane osobowe wychodzą poza bazę."""
    probny(firma("jan@gmail.com", "Pierwsza"), django_capture_on_commit_callbacks)

    probny(firma("jan+bot@gmail.com", "Druga"), django_capture_on_commit_callbacks)

    wiadomosc = mail.outbox[0].body + mail.outbox[0].subject
    assert "jan" not in wiadomosc and "gmail" not in wiadomosc


def test_inna_skrzynka_nie_zglasza_sie(django_capture_on_commit_callbacks):
    probny(firma("jan@gmail.com", "Pierwsza"), django_capture_on_commit_callbacks)

    probny(firma("anna@gmail.com", "Druga"), django_capture_on_commit_callbacks)

    assert mail.outbox == []


def test_ta_sama_firma_nie_zglasza_sama_siebie(django_capture_on_commit_callbacks):
    """Wykluczenie własnego wiersza - inaczej każdy pierwszy okres byłby powtórką."""
    tenant = firma("jan@gmail.com")
    tenant.skrot_skrzynki = skrot_skrzynki("jan@gmail.com")
    tenant.save(update_fields=["skrot_skrzynki"])

    probny(tenant, django_capture_on_commit_callbacks)

    assert mail.outbox == []


def test_adres_bez_sensu_nie_wywraca_rejestracji(django_capture_on_commit_callbacks):
    tenant = firma("nieadres")

    subskrypcja = probny(tenant, django_capture_on_commit_callbacks)

    tenant.refresh_from_db()
    assert subskrypcja.pk is not None
    assert tenant.skrot_skrzynki == ""
    assert mail.outbox == []


def test_awaria_wykrywania_nie_zabiera_klientowi_okresu_probnego(
    django_capture_on_commit_callbacks, mocker
):
    """
    Klient właśnie potwierdził adres i czeka na konto.

    Nasza ciekawość, skąd przyszedł, jest mniej warta niż to, żeby konto
    w ogóle powstało - więc błąd w wykrywaniu ma zostać w logu, a nie
    w odpowiedzi HTTP.
    """
    mocker.patch("api.views.accounts.skrot_skrzynki", side_effect=RuntimeError("padło"))
    tenant = firma("jan@gmail.com")

    subskrypcja = probny(tenant, django_capture_on_commit_callbacks)

    assert subskrypcja.pk is not None
    assert Subscription.objects.filter(tenant=tenant).exists()


def test_wycofana_rejestracja_nie_zglasza_firmy_ktora_nie_powstala(
    django_capture_on_commit_callbacks,
):
    """
    Zgłoszenie idzie dopiero po zatwierdzeniu transakcji.

    Bez tego alarm potrafiłby wskazywać numer firmy, której nie ma w bazie,
    a operator szukałby jej w panelu administracyjnym bez skutku.
    """
    probny(firma("jan@gmail.com", "Pierwsza"), django_capture_on_commit_callbacks)

    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                druga = firma("jan+bot@gmail.com", "Druga")
                zalozenie_okresu_probnego(druga)
                raise RuntimeError("rejestracja przerwana")
        except RuntimeError:
            pass

    assert mail.outbox == []
    assert not Tenant.objects.filter(name="Druga").exists()


def test_zadanie_zlecane_jest_pilnowane_osobno():
    """
    Rejestracji zadania NIE da się sprawdzić w tym procesie.

    Asercja `"accounts.tasks_probne..." in app.tasks` napisana tutaj przechodzi
    także wtedy, gdy import w `accounts/tasks.py` zniknie - bo w procesie
    pytest moduł wczytuje ten plik testowy i sam widok. Sprawdziłem to
    mutacją: usunięcie importu nie zapaliło czerwonego.

    Pilnuje tego `test_rejestracja_zadan.py`, który startuje Django i Celery
    w osobnym procesie, dokładnie tak jak worker. Ten test istnieje po to,
    żeby następna osoba nie dopisała tu tej łatwiejszej, bezużytecznej wersji.
    """
    from accounts import tasks

    assert "tasks_probne" in tasks.__dict__, (
        "Zadanie musi być zaimportowane w accounts/tasks.py, bo Celery odkrywa "
        "automatycznie tylko moduły o tej nazwie. Czy worker naprawdę je zna, "
        "sprawdza accounts/tests/test_rejestracja_zadan.py w osobnym procesie."
    )
