"""
Ślad ostatniego użycia witryny zapisywany najwyżej raz na godzinę (audyt 2026-10, P21).

Ustawienia widgetu wczytuje każde wyświetlenie strony klienta, a każde
wczytanie zapisywało `last_seen` znanej witryny - UPDATE tego samego wiersza
przy każdym odsłonięciu strony, na ruchliwej witrynie setki na godzinę.
`last_seen` służy do rozpoznania witryn, które przestały działać; godzina
dokładności wystarcza do tego z dużym zapasem.
"""

from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Subscription, Tenant, WidgetDomain


@pytest.fixture
def firma(db):
    tenant = Tenant.objects.create(name="Witryna")
    Subscription.objects.create(
        tenant=tenant,
        plan_type="start",
        is_active=True,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
    )
    return tenant


def wczytaj_widget(tenant):
    return APIClient().get(
        "/api/widget-settings/", HTTP_X_API_KEY=str(tenant.api_key), HTTP_ORIGIN="https://klient.pl"
    )


def zapisy_domeny(zapytania):
    return [
        q
        for q in zapytania.captured_queries
        if q["sql"].startswith('UPDATE "accounts_widgetdomain"')
    ]


@pytest.mark.django_db
def test_swiezy_slad_nie_jest_zapisywany_przy_kazdym_wczytaniu(firma):
    WidgetDomain.objects.create(tenant=firma, host="klient.pl")

    with CaptureQueriesContext(connection) as zapytania:
        for _ in range(3):
            assert wczytaj_widget(firma).status_code == 200

    assert zapisy_domeny(zapytania) == []


@pytest.mark.django_db
def test_slad_starszy_niz_godzina_jest_odswiezany_raz(firma):
    domena = WidgetDomain.objects.create(tenant=firma, host="klient.pl")
    dawno = timezone.now() - timedelta(hours=2)
    WidgetDomain.objects.filter(pk=domena.pk).update(last_seen=dawno)

    with CaptureQueriesContext(connection) as zapytania:
        for _ in range(3):
            wczytaj_widget(firma)

    assert len(zapisy_domeny(zapytania)) == 1
    domena.refresh_from_db()
    assert domena.last_seen > timezone.now() - timedelta(minutes=1)
