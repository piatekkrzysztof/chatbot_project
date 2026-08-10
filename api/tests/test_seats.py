"""
Limit kont w firmie.

Cennik obiecuje 1, 3 albo 10 miejsc zależnie od planu, ale nic tego nie
pilnowało — klient planu Start mógł zaprosić dowolną liczbę pracowników.
Bez tej kontroli wyższy plan kupowało się wyłącznie po limit wiadomości.
"""
import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from accounts.models import CustomUser, InvitationToken
from accounts.seats import limit_miejsc, sprawdz_limit_miejsc, wolne_miejsca


def dodaj_konta(tenant, ile):
    for numer in range(ile):
        CustomUser.objects.create_user(
            username=f"pracownik{numer}@example.com",
            email=f"pracownik{numer}@example.com",
            password="tajne123",
            tenant=tenant,
            role="employee",
        )


@pytest.mark.django_db
class TestLimituZKatalogu:
    @pytest.mark.parametrize("plan,miejsca", [
        ("start", 1), ("grow", 3), ("pro", 10),
    ])
    def test_limit_pochodzi_z_cennika(self, tenant, subscribtion, plan, miejsca):
        subscribtion.plan_type = plan
        subscribtion.save()

        assert limit_miejsc(tenant) == miejsca

    def test_nieznany_plan_nie_jest_ograniczany(self, tenant, subscribtion):
        """
        Firma w okresie próbnym nie ma jeszcze subskrypcji, a plan sprzed
        cennika może nazywać się dowolnie. Limit jednego miejsca zablokowałby
        im zapraszanie pracowników, zanim w ogóle zdecydują o zakupie —
        a dodatkowe konto nic nas nie kosztuje.
        """
        subscribtion.plan_type = "Prymium"
        subscribtion.save()

        assert limit_miejsc(tenant) is None
        sprawdz_limit_miejsc(tenant)

    def test_brak_subskrypcji_nie_blokuje(self, tenant):
        assert limit_miejsc(tenant) is None
        sprawdz_limit_miejsc(tenant)

    def test_wolne_miejsca_nie_schodza_ponizej_zera(self, tenant, subscribtion):
        """
        Firma może mieć więcej kont niż limit, jeśli zeszła na niższy plan.
        Nie odbieramy nikomu konta — blokujemy wyłącznie dodawanie nowych.
        """
        subscribtion.plan_type = "start"
        subscribtion.save()
        dodaj_konta(tenant, 4)

        assert wolne_miejsca(tenant) == 0


@pytest.mark.django_db
class TestSprawdzania:
    def test_wolne_miejsce_przechodzi(self, tenant, subscribtion):
        subscribtion.plan_type = "grow"
        subscribtion.save()
        dodaj_konta(tenant, 1)

        sprawdz_limit_miejsc(tenant)

    def test_brak_miejsca_zatrzymuje(self, tenant, subscribtion, user):
        subscribtion.plan_type = "start"
        subscribtion.save()
        user.tenant = tenant
        user.save()

        with pytest.raises(ValidationError):
            sprawdz_limit_miejsc(tenant)

    def test_komunikat_podaje_liczbe_i_wyjscie(self, tenant, subscribtion, user):
        subscribtion.plan_type = "start"
        subscribtion.save()
        user.tenant = tenant
        user.save()

        with pytest.raises(ValidationError) as blad:
            sprawdz_limit_miejsc(tenant)

        assert "wyższy plan" in str(blad.value)


@pytest.mark.django_db
class TestEgzekwowaniaWZaproszeniach:
    URL = "/api/accounts/invitations/"

    def wlasciciel(self, user, tenant, plan):
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

    def test_start_nie_zaprosi_drugiej_osoby(self, user, tenant, subscribtion):
        """Właściciel zajmuje jedyne miejsce planu Start."""
        klient = self.wlasciciel(user, tenant, "start")

        response = klient.post(
            self.URL, {"email": "nowy@example.com", "role": "employee"}, format="json"
        )

        assert response.status_code == 400
        assert not InvitationToken.objects.exists()

    def test_grow_zaprosi(self, user, tenant, subscribtion):
        klient = self.wlasciciel(user, tenant, "grow")

        response = klient.post(
            self.URL, {"email": "nowy@example.com", "role": "employee"}, format="json"
        )

        assert response.status_code in (200, 201)
        assert InvitationToken.objects.count() == 1

    def test_zaproszenie_traci_waznosc_gdy_miejsca_sie_zapelnia(
        self, user, tenant, subscribtion
    ):
        """
        Sedno drugiego sprawdzenia. Zaproszenie wystawione, gdy miejsce było
        wolne, nie może dawać konta po tym, jak miejsca się zapełniły.
        """
        subscribtion.plan_type = "grow"
        subscribtion.save()
        user.tenant = tenant
        user.save()
        zaproszenie = InvitationToken.objects.create(
            tenant=tenant, email="nowy@example.com", role="employee",
        )
        # Miejsca zapełniają się po wystawieniu zaproszenia
        dodaj_konta(tenant, 2)

        response = APIClient().post(
            "/api/accounts/accept-invite/",
            {
                "token": str(zaproszenie.token),
                "username": "nowy@example.com",
                "email": "nowy@example.com",
                "password": "tajne123",
            },
            format="json",
        )

        assert response.status_code == 400
        assert not CustomUser.objects.filter(email="nowy@example.com").exists()
