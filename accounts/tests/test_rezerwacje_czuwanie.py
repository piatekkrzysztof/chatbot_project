"""
Bilety pracy AI, których nikt nie rozliczył.

Kategoria ryzyka: NARZĘDZIE, KTÓREGO NIKT NIE WOŁA. `check_message_reservations`
umiała wypisać nierozliczone bilety od #44 i sprzątać rozliczone. Nie było jej
w harmonogramie ani w żadnym alarmie, więc przez cały ten czas nie zrobiła
żadnej z tych dwóch rzeczy ani razu.

To o stopień gorszy wariant awarii z 2.14.1. Tamte trzy zadania przynajmniej
były w harmonogramie i beat je zlecał - wystarczyło zajrzeć do logu workera,
żeby zobaczyć „Received unregistered task". Tutaj nie było czego zobaczyć:
brak wpisu nie zostawia po sobie żadnego śladu.

Testy pilnują trzech rzeczy: że zadanie w ogóle jest wołane, że alarmuje
dokładnie wtedy, gdy jest co rozliczać, i że sprzątanie nie zabiera niczego
poza biletami z zamkniętym wynikiem sprzed kwartału.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from accounts import rezerwacje
from accounts.czuwanie import BrakAdresuAlertow
from accounts.models import MessageReservation
from accounts.tasks_rezerwacje import NAJWIECEJ_W_ALERCIE, czuwaj_nad_rezerwacjami

pytestmark = pytest.mark.django_db

NAZWA_ZADANIA = "accounts.tasks_rezerwacje.czuwaj_nad_rezerwacjami"


@pytest.fixture(autouse=True)
def adres_alertow(settings):
    """Alerty muszą mieć dokąd iść niezależnie od .env dewelopera."""
    settings.EMAIL_ALERTOW = "alerty@example.com"


def bilet(tenant, *, stan, wiek=None, wygasl=None, subskrypcja=None, cycle_id=None):
    """
    Bilet o zadanym stanie i wieku.

    `created_at` jest `auto_now_add`, więc wiek ustawiamy osobnym UPDATE-em -
    inaczej każdy bilet powstawałby „teraz" i granice wieku nie dałyby się
    sprawdzić.

    `finished` ustawiamy tak, jak robi to `Reservation.settle`, a nie tak, jak
    podpowiada intuicja. Bilet `uncertain` ma `finished=True`: `settle(None)`
    przechodzi przez `if not billable`, bo `None` jest fałszywe, i dopiero
    potem wpisuje stan. Pierwsza wersja tego pomocnika dawała mu `False`
    i przez to test ochrony nierozliczonych biletów sprawdzał nie ten warunek,
    co trzeba - kasowanie ich wyglądałoby na zablokowane przez `finished`,
    choć naprawdę blokuje je wyłącznie lista stanów. Wyszło przy mutacji.
    Tylko `pending` jest niedokończony, bo nikt go jeszcze nie rozliczał.
    """
    teraz = timezone.now()
    row = MessageReservation.objects.create(
        tenant=tenant,
        subscription=subskrypcja,
        cycle_id=cycle_id if cycle_id is not None else (uuid.uuid4() if subskrypcja else None),
        state=stan,
        finished=stan != "pending",
        expires_at=teraz - (wygasl if wygasl is not None else timedelta(minutes=1)),
    )
    if wiek is not None:
        MessageReservation.objects.filter(pk=row.pk).update(created_at=teraz - wiek)
        row.refresh_from_db()
    return row


# --- czy ktokolwiek to woła -------------------------------------------------


def test_zadanie_jest_w_harmonogramie():
    """
    Cała reszta tego pliku nie ma znaczenia, jeśli nikt zadania nie zleca.

    To jest ten jeden test, który padał na kodzie sprzed tej zmiany: kod
    sprzątania i raportowania istniał, tylko nic go nie uruchamiało.
    """
    from chatbot_project.celery import app

    zlecane = {wpis["task"] for wpis in app.conf.beat_schedule.values()}
    assert NAZWA_ZADANIA in zlecane


# --- kiedy alarm idzie, a kiedy nie -----------------------------------------


def test_niepewny_bilet_wywoluje_alert(tenant):
    bilet(tenant, stan="uncertain")

    wynik = czuwaj_nad_rezerwacjami()

    assert wynik["nierozliczone"] == 1
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["alerty@example.com"]


def test_przeterminowany_pending_tez_wywoluje_alert(tenant):
    """
    Klient, który po awarii zamilkł, nigdy nie dostanie stanu `uncertain`.

    `reserve_message` przestawia przeterminowane bilety dopiero przy kolejnej
    wiadomości tej samej firmy. U firmy, która odeszła, bilet zostaje
    w `pending` na zawsze - i właśnie ten przypadek najłatwiej przeoczyć.
    """
    bilet(tenant, stan="pending", wygasl=timedelta(hours=2))

    assert czuwaj_nad_rezerwacjami()["nierozliczone"] == 1
    assert len(mail.outbox) == 1


def test_pending_przed_terminem_nie_jest_zglaszany(tenant):
    """Trwająca odpowiedź to nie jest bilet do rozliczenia."""
    teraz = timezone.now()
    MessageReservation.objects.create(
        tenant=tenant, state="pending", expires_at=teraz + timedelta(minutes=5)
    )

    assert czuwaj_nad_rezerwacjami()["nierozliczone"] == 0
    assert mail.outbox == []


def test_rozliczone_bilety_nie_sa_zglaszane(tenant):
    bilet(tenant, stan="charged")
    bilet(tenant, stan="released")

    assert czuwaj_nad_rezerwacjami()["nierozliczone"] == 0
    assert mail.outbox == []


def test_brak_biletow_nie_wysyla_niczego(tenant):
    """Alert, który przychodzi bez powodu, przestaje być czytany."""
    assert czuwaj_nad_rezerwacjami() == {"nierozliczone": 0, "usuniete": 0}
    assert mail.outbox == []


def test_alert_wymienia_bilet_i_komende_do_rozliczenia(tenant):
    row = bilet(tenant, stan="uncertain")

    czuwaj_nad_rezerwacjami()

    tresc = mail.outbox[0].body
    assert str(row.pk) in tresc
    assert "check_message_reservations --reservation" in tresc


def test_alert_mowi_o_biletach_ponad_liste(tenant):
    """Lista w wiadomości jest ucięta, ale liczba nie może być."""
    for _ in range(NAJWIECEJ_W_ALERCIE + 3):
        bilet(tenant, stan="uncertain")

    wynik = czuwaj_nad_rezerwacjami()

    assert wynik["nierozliczone"] == NAJWIECEJ_W_ALERCIE + 3
    assert f"{NAJWIECEJ_W_ALERCIE + 3}" in mail.outbox[0].subject
    assert "oraz 3 dalszych" in mail.outbox[0].body


def test_brak_adresu_alertow_przerywa_zamiast_wysylac_donikad(tenant, settings):
    """
    `send_mail` z pustym odbiorcą zwraca zero i nie zgłasza błędu.

    Ta sama pułapka raz już wyciszyła cały monitoring odmów widgetu.
    """
    settings.EMAIL_ALERTOW = ""
    settings.DEFAULT_FROM_EMAIL = ""
    bilet(tenant, stan="uncertain")

    with pytest.raises(BrakAdresuAlertow):
        czuwaj_nad_rezerwacjami()


def test_nieudana_wysylka_nie_uchodzi_za_doreczona(tenant):
    bilet(tenant, stan="uncertain")

    with patch("accounts.tasks_rezerwacje.send_mail", return_value=0):
        with pytest.raises(RuntimeError):
            czuwaj_nad_rezerwacjami()


# --- sprzątanie rozliczonych ------------------------------------------------


def test_sprzatanie_usuwa_rozliczone_sprzed_okresu(tenant):
    stary = bilet(tenant, stan="charged", wiek=rezerwacje.OKRES_ROZLICZONYCH + timedelta(days=1))

    assert czuwaj_nad_rezerwacjami()["usuniete"] == 1
    assert not MessageReservation.objects.filter(pk=stary.pk).exists()


def test_sprzatanie_zostawia_bilety_mlodsze_niz_okres(tenant):
    swiezy = bilet(tenant, stan="charged", wiek=rezerwacje.OKRES_ROZLICZONYCH - timedelta(days=1))

    assert czuwaj_nad_rezerwacjami()["usuniete"] == 0
    assert MessageReservation.objects.filter(pk=swiezy.pk).exists()


def test_sprzatanie_nie_rusza_nierozliczonych(tenant):
    """
    Wiek nie może skasować biletu, którego nikt nie rozliczył.

    Usunięcie go wyglądałoby jak załatwienie sprawy, a byłoby jej cichym
    porzuceniem: pytanie, czy klient zapłacił za pracę, której nie dostał,
    zniknęłoby razem z wierszem.
    """
    stary = bilet(tenant, stan="uncertain", wiek=rezerwacje.OKRES_ROZLICZONYCH * 10)

    wynik = czuwaj_nad_rezerwacjami()

    assert wynik["usuniete"] == 0
    assert wynik["nierozliczone"] == 1
    assert MessageReservation.objects.filter(pk=stary.pk).exists()


def test_sprzatanie_obejmuje_bilety_czatu_testowego(tenant):
    """
    Bilety bez subskrypcji też mają zniknąć.

    Czat testowy tworzy je bez subskrypcji, a warunek pomijający bieżący cykl
    porównuje `billing_cycle_id` z `cycle_id` - przy obu pustych porównanie
    w SQL daje NULL, nie prawdę. Gdyby to poszło w drugą stronę, najliczniejsze
    bilety w bazie nie byłyby sprzątane nigdy.
    """
    stary = bilet(
        tenant,
        stan="released",
        wiek=rezerwacje.OKRES_ROZLICZONYCH + timedelta(days=1),
    )
    assert stary.subscription_id is None

    assert czuwaj_nad_rezerwacjami()["usuniete"] == 1
    assert not MessageReservation.objects.filter(pk=stary.pk).exists()


def test_sprzatanie_zostawia_bilety_z_biezacego_cyklu(tenant, subscribtion):
    """Z tych biletów liczy się zużycie, które klient widzi w panelu."""
    biezacy = bilet(
        tenant,
        stan="charged",
        wiek=rezerwacje.OKRES_ROZLICZONYCH + timedelta(days=1),
        subskrypcja=subscribtion,
        cycle_id=subscribtion.billing_cycle_id,
    )

    assert czuwaj_nad_rezerwacjami()["usuniete"] == 0
    assert MessageReservation.objects.filter(pk=biezacy.pk).exists()


def test_sprzatanie_przechodzi_przez_wiele_partii(tenant):
    """Partia mniejsza niż liczba wierszy nie może zostawić reszty na jutro."""
    for _ in range(5):
        bilet(tenant, stan="charged", wiek=rezerwacje.OKRES_ROZLICZONYCH + timedelta(days=1))

    assert rezerwacje.usun_rozliczone(partia=2) == 5
    assert not MessageReservation.objects.exists()


def test_sprzatanie_dzieje_sie_mimo_nieudanego_alertu(tenant):
    """
    Niedziałająca poczta nie może zatrzymać sprzątania.

    Alert i sprzątanie to dwie niezależne sprawy; gdyby wysyłka szła pierwsza,
    jedna zepsuta zmienna środowiskowa wstrzymałaby usuwanie danych na tak
    długo, jak długo nikt by tego nie zauważył.
    """
    stary = bilet(tenant, stan="charged", wiek=rezerwacje.OKRES_ROZLICZONYCH + timedelta(days=1))
    bilet(tenant, stan="uncertain")

    with patch("accounts.tasks_rezerwacje.send_mail", side_effect=OSError("poczta padła")):
        with pytest.raises(OSError):
            czuwaj_nad_rezerwacjami()

    assert not MessageReservation.objects.filter(pk=stary.pk).exists()


def test_okres_jest_tym_zatwierdzonym():
    """
    Okres przechowywania jest decyzją, nie porządkami w kodzie.

    Testy granic wyliczają wiek z tej samej stałej, więc same w sobie
    przeszłyby przy każdej wartości. Ten test przypina konkretną liczbę.
    """
    assert rezerwacje.OKRES_ROZLICZONYCH == timedelta(days=90)
