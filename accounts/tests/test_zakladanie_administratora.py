"""
Zakladanie konta administratora platformy.

Kategoria ryzyka: WEJSCIE. Nie chodzi o bezpieczenstwo, tylko o to, ze
`createsuperuser` to odruch znany z kazdego projektu Django. Gdy konczy sie
surowym bledem bazy o ograniczeniu NOT NULL, obcy developer nie ma jak
zgadnac, ze w tym projekcie kazdy uzytkownik musi nalezec do firmy.

Drugi test w tym pliku jest wazniejszy od pierwszego: pilnuje, zeby ta wygoda
NIE rozlala sie na zwyklych uzytkownikow. Pole `tenant` niesie cala izolacje
najemcow -- gdyby ktos kiedys "uproscil" to, domyslnie podstawiajac firme
kazdemu zakladanemu kontu, rozdzielenie danych miedzy klientami przestaloby
cokolwiek znaczyc, a zaden istniejacy test by tego nie zauwazyl.
"""

import pytest
from django.db import IntegrityError, transaction

from accounts.models import FIRMA_ADMINISTRACYJNA, CustomUser, Tenant, UserRole


@pytest.mark.django_db
class TestAdministratora:
    def test_createsuperuser_dziala_bez_podawania_firmy(self):
        admin = CustomUser.objects.create_superuser(
            username="admin", email="admin@example.com", password="tajne-haslo-123"
        )

        assert admin.tenant is not None
        assert admin.tenant.name == FIRMA_ADMINISTRACYJNA
        assert admin.is_superuser and admin.is_staff

    def test_administrator_nie_dostaje_roli_viewer(self):
        # Domyslna wartosc pola to `viewer`, wiec bez jawnego ustawienia
        # administrator mogl w adminie wszystko, a w panelu nie mogl nic
        # zapisac. Sprzecznosc, ktora wyglada na zepsute uprawnienia.
        admin = CustomUser.objects.create_superuser(
            username="admin", email="admin@example.com", password="tajne-haslo-123"
        )

        assert admin.role == UserRole.OWNER

    def test_kolejni_administratorzy_dziela_jedna_firme(self):
        # Firma na kazdego administratora zasmiecalaby liste najemcow
        # i mylila sie z prawdziwymi klientami.
        pierwszy = CustomUser.objects.create_superuser(
            username="admin1", email="a1@example.com", password="tajne-haslo-123"
        )
        drugi = CustomUser.objects.create_superuser(
            username="admin2", email="a2@example.com", password="tajne-haslo-123"
        )

        assert pierwszy.tenant_id == drugi.tenant_id
        assert Tenant.objects.filter(name=FIRMA_ADMINISTRACYJNA).count() == 1

    def test_podana_firma_ma_pierwszenstwo(self):
        # Administrator zakladany dla konkretnego klienta ma trafic do niego,
        # a nie do firmy administracyjnej.
        klient = Tenant.objects.create(name="Rowerownia Krakowska")

        admin = CustomUser.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="tajne-haslo-123",
            tenant=klient,
        )

        assert admin.tenant_id == klient.id

    def test_zwykly_uzytkownik_NADAL_wymaga_firmy(self):
        """
        Najwazniejszy test w tym pliku.

        Uproszczenie dotyczy wylacznie administratorow platformy. Konto bez
        firmy przechodzace przez zwykla sciezke zakladania oznaczaloby
        uzytkownika poza izolacja najemcow: TenantMiddleware odmawia przy
        pustym tenant_id, ale samo istnienie takiego konta to stan, ktorego
        reszta kodu sie nie spodziewa.
        """
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CustomUser.objects.create_user(username="bez-firmy", password="tajne-haslo-123")
