"""
Alerty o zużyciu limitu wiadomości.

Wyczerpanie limitu wyglądało z zewnątrz jak awaria chatbota: widget przestawał
odpowiadać, a klient dowiadywał się o tym od własnych odwiedzających — albo
wcale. Alert ma zamienić cichą awarię w decyzję: dokupić pakiet, przejść wyżej
albo świadomie poczekać do nowego cyklu.
"""
import pytest
from django.core import mail

from accounts.models import Subscription
from accounts.tasks import powiadom_o_zuzyciu


@pytest.fixture
def subskrypcja(subscribtion):
    subscribtion.message_limit = 100
    subscribtion.current_message_count = 0
    subscribtion.alert_threshold_sent = 0
    subscribtion.save()
    return subscribtion


@pytest.mark.django_db
class TestWykrywaniaProgu:
    @pytest.mark.parametrize("uzyte,oczekiwany", [
        (0, None), (50, None), (79, None),
        (80, 80), (94, 80),
        (95, 95), (99, 95),
        (100, 100), (150, 100),
    ])
    def test_prog_dla_zuzycia(self, subskrypcja, uzyte, oczekiwany):
        subskrypcja.current_message_count = uzyte

        assert subskrypcja.prog_do_powiadomienia() == oczekiwany

    def test_ten_sam_prog_nie_powtarza_sie(self, subskrypcja):
        """
        Bez tego alert leciałby przy każdej kolejnej wiadomości powyżej progu,
        a klient nauczyłby się je ignorować dokładnie wtedy, gdy zaczynają
        być ważne.
        """
        subskrypcja.current_message_count = 85
        subskrypcja.alert_threshold_sent = 80

        assert subskrypcja.prog_do_powiadomienia() is None

    def test_skok_zuzycia_daje_jeden_alert_o_najwyzszym_progu(self, subskrypcja):
        """Przy skokowym zużyciu klient ma dostać jedną wiadomość, nie trzy."""
        subskrypcja.current_message_count = 100

        assert subskrypcja.prog_do_powiadomienia() == 100

    def test_brak_limitu_nie_wywraca_obliczen(self, subskrypcja):
        subskrypcja.message_limit = 0

        assert subskrypcja.usage_percent() == 0
        assert subskrypcja.prog_do_powiadomienia() is None

    def test_nowy_cykl_zeruje_prog(self, subskrypcja):
        """
        Bez wyzerowania klient nie dostałby już nigdy żadnego alertu: w nowym
        cyklu zużycie startuje od zera i nic nie przekroczyłoby progu
        zapamiętanego z poprzedniego miesiąca.
        """
        subskrypcja.current_message_count = 100
        subskrypcja.alert_threshold_sent = 100
        subskrypcja.save()

        subskrypcja.reset_usage()

        assert subskrypcja.alert_threshold_sent == 0


@pytest.mark.django_db
class TestWysylkiPrzyZliczaniu:
    def test_przekroczenie_progu_wysyla_wiadomosc(self, subskrypcja, tenant):
        tenant.owner_email = "wlasciciel@example.com"
        tenant.save()
        subskrypcja.current_message_count = 79
        subskrypcja.save()

        subskrypcja.increment_usage()

        assert len(mail.outbox) == 1
        assert "80%" in mail.outbox[0].subject

    def test_kolejne_wiadomosci_nie_zasypuja_skrzynki(self, subskrypcja, tenant):
        tenant.owner_email = "wlasciciel@example.com"
        tenant.save()
        subskrypcja.current_message_count = 79
        subskrypcja.save()

        for _ in range(10):
            subskrypcja.increment_usage()

        assert len(mail.outbox) == 1

    def test_prog_zapisuje_sie_nawet_gdy_poczta_padnie(self, subskrypcja, tenant, mocker):
        """
        Zapisujemy próg przed wysyłką. Inaczej awaria poczty zamieniłaby jeden
        alert w alert przy każdej kolejnej wiadomości.
        """
        tenant.owner_email = "wlasciciel@example.com"
        tenant.save()
        mocker.patch("accounts.tasks.send_mail", side_effect=RuntimeError("SMTP padł"))
        subskrypcja.current_message_count = 79
        subskrypcja.save()

        subskrypcja.increment_usage()

        subskrypcja.refresh_from_db()
        assert subskrypcja.alert_threshold_sent == 80

    def test_awaria_poczty_nie_wywraca_odpowiedzi(self, subskrypcja, tenant, mocker):
        """Alert jest ważny, ale nie ważniejszy niż odpowiedź dla odwiedzającego."""
        tenant.owner_email = "wlasciciel@example.com"
        tenant.save()
        mocker.patch("accounts.tasks.send_mail", side_effect=RuntimeError("SMTP padł"))
        subskrypcja.current_message_count = 79
        subskrypcja.save()

        subskrypcja.increment_usage()

        subskrypcja.refresh_from_db()
        assert subskrypcja.current_message_count == 80

    def test_ponizej_progu_nic_nie_wysylamy(self, subskrypcja, tenant):
        tenant.owner_email = "wlasciciel@example.com"
        tenant.save()
        subskrypcja.current_message_count = 10
        subskrypcja.save()

        subskrypcja.increment_usage()

        assert mail.outbox == []


@pytest.mark.django_db
class TestTresciWiadomosci:
    @pytest.mark.parametrize("prog,fragment", [
        (80, "uprzedzenie"),
        (95, "przestanie odpowiadać"),
        (100, "nie odpowiada już"),
    ])
    def test_tresc_zalezy_od_progu(self, subskrypcja, tenant, prog, fragment):
        """
        Trzy różne sytuacje: uprzedzenie, ostrzeżenie i informacja o tym,
        że bot już milczy. Jednakowa treść zacierałaby tę różnicę.
        """
        tenant.owner_email = "wlasciciel@example.com"
        tenant.save()

        powiadom_o_zuzyciu(subskrypcja.pk, prog)

        assert fragment in mail.outbox[0].body

    def test_wiadomosc_prowadzi_do_panelu(self, subskrypcja, tenant):
        tenant.owner_email = "wlasciciel@example.com"
        tenant.save()

        powiadom_o_zuzyciu(subskrypcja.pk, 100)

        assert "/subskrypcja" in mail.outbox[0].body

    def test_brak_adresu_nie_wywraca_zadania(self, subskrypcja, tenant):
        tenant.owner_email = ""
        tenant.save()

        powiadom_o_zuzyciu(subskrypcja.pk, 80)

        assert mail.outbox == []

    def test_usunieta_subskrypcja_nie_wywraca_zadania(self, subskrypcja):
        """Zadanie w kolejce może wykonać się po usunięciu firmy."""
        pk = subskrypcja.pk
        Subscription.objects.filter(pk=pk).delete()

        powiadom_o_zuzyciu(pk, 80)

        assert mail.outbox == []
