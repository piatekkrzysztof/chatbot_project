"""
Minimalizacja i retencja danych osobowych zbieranych przy rozmowach.

Rozmowa odwiedzającego to dane osobowe: treść pytań, adres IP i kontakt
zostawiony w formularzu eskalacji. Bez tych mechanizmów aplikacja trzymałaby
je bezterminowo i w pełnej postaci, czego RODO nie dopuszcza.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from chat.models import ChatMessage, ChatUsageLog, ContactRequest, Conversation, PromptLog
from chat.privacy import anonymize_ip
from chat.retention import purge_all_tenants, purge_tenant


class TestAnonimizacjaIP:
    def test_ipv4_traci_ostatni_oktet(self):
        assert anonymize_ip("192.168.18.7") == "192.168.18.0"

    def test_ipv6_traci_koncowke(self):
        assert anonymize_ip("2001:db8::1234:5678") == "2001:db8::"

    @pytest.mark.parametrize("raw", ["", None, "nie-adres", "192.168.0.1, 10.0.0.1"])
    def test_smieci_nie_trafiaja_do_bazy(self, raw):
        """Nagłówek od proxy bywa listą adresów — nic niesprawdzonego nie zapisujemy."""
        assert anonymize_ip(raw) == "unknown"


def _old_conversation(tenant, days_ago):
    conversation = Conversation.objects.create(
        tenant=tenant, user_identifier="192.168.0.0"
    )
    ChatMessage.objects.create(
        conversation=conversation, sender="user", message="Moje pytanie"
    )
    stamp = timezone.now() - timedelta(days=days_ago)
    # auto_now/auto_now_add pomijają zwykły save(), stąd update() na queryset
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=stamp)
    return conversation, stamp


@pytest.mark.django_db
class TestRetencja:
    def test_stare_rozmowy_znikaja_wraz_z_wiadomosciami(self, tenant):
        tenant.data_retention_days = 30
        tenant.save()
        _old_conversation(tenant, days_ago=45)

        purge_tenant(tenant)

        assert Conversation.objects.filter(tenant=tenant).count() == 0
        assert ChatMessage.objects.count() == 0

    def test_raport_liczy_kazdy_model_osobno(self, tenant):
        """
        delete() zwraca sumę razem z kaskadami, więc naiwny licznik pokazywał
        "Conversation: 2" dla jednej rozmowy z jedną wiadomością. Raport, któremu
        nie można ufać, jest gorszy niż jego brak — na nim opiera się dowód, że
        polityka retencji faktycznie zadziałała.
        """
        tenant.data_retention_days = 30
        tenant.save()
        _old_conversation(tenant, days_ago=45)

        removed = purge_tenant(tenant)

        assert removed["Conversation"] == 1
        assert removed["ChatMessage"] == 1

    def test_swieze_rozmowy_zostaja(self, tenant):
        tenant.data_retention_days = 30
        tenant.save()
        _old_conversation(tenant, days_ago=5)

        purge_tenant(tenant)

        assert Conversation.objects.filter(tenant=tenant).count() == 1

    def test_logi_promptow_nie_przezywaja_rozmowy(self, tenant):
        """
        PromptLog wskazuje konwersację przez SET_NULL, więc kasowanie rozmowy
        samo w sobie zostawiłoby treść pytań w bazie — żądanie usunięcia byłoby
        spełnione tylko pozornie.
        """
        tenant.data_retention_days = 30
        tenant.save()
        conversation, stamp = _old_conversation(tenant, days_ago=45)
        log = PromptLog.objects.create(
            tenant=tenant, conversation=conversation, model="test",
            prompt="Dane wrazliwe", response="odpowiedz", source="gpt",
        )
        PromptLog.objects.filter(pk=log.pk).update(created_at=stamp)

        purge_tenant(tenant)

        assert PromptLog.objects.filter(tenant=tenant).count() == 0

    def test_zostawione_kontakty_tez_wygasaja(self, tenant):
        tenant.data_retention_days = 30
        tenant.save()
        request = ContactRequest.objects.create(
            tenant=tenant, name="Jan", contact="jan@example.com"
        )
        ContactRequest.objects.filter(pk=request.pk).update(
            created_at=timezone.now() - timedelta(days=45)
        )

        purge_tenant(tenant)

        assert ContactRequest.objects.filter(tenant=tenant).count() == 0

    def test_zero_dni_wylacza_usuwanie(self, tenant):
        """Klient może świadomie zrezygnować z automatycznego kasowania."""
        tenant.data_retention_days = 0
        tenant.save()
        _old_conversation(tenant, days_ago=999)

        purge_tenant(tenant)

        assert Conversation.objects.filter(tenant=tenant).count() == 1

    def test_retencja_nie_siega_do_innego_klienta(self, tenant):
        from api.tests.factories import TenantFactory

        obcy = TenantFactory()
        obcy.data_retention_days = 0
        obcy.save()
        tenant.data_retention_days = 30
        tenant.save()

        _old_conversation(tenant, days_ago=45)
        _old_conversation(obcy, days_ago=45)

        purge_all_tenants()

        assert Conversation.objects.filter(tenant=tenant).count() == 0
        assert Conversation.objects.filter(tenant=obcy).count() == 1

    def test_blad_jednego_klienta_nie_zatrzymuje_reszty(self, tenant, monkeypatch):
        from api.tests.factories import TenantFactory
        from chat import retention

        TenantFactory()
        tenant.data_retention_days = 30
        tenant.save()
        _old_conversation(tenant, days_ago=45)

        oryginal = retention.purge_tenant
        wywolania = {"n": 0}

        def czasem_wybucha(t, now=None):
            wywolania["n"] += 1
            if wywolania["n"] == 1:
                raise RuntimeError("awaria bazy")
            return oryginal(t, now=now)

        monkeypatch.setattr(retention, "purge_tenant", czasem_wybucha)
        retention.purge_all_tenants()

        assert wywolania["n"] == 2
