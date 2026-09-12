from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier

import pytest
from django.contrib import admin
from django.db import close_old_connections, connection, connections
from django.test import Client, RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from accounts import dwuskladnikowe, totp
from accounts.models import CustomUser, DrugiSkladnik, Tenant

PASSWORD = "Independent!Passphrase739"


@pytest.fixture
def account(db):
    user = CustomUser.objects.create_user(
        username="mfa@example.com",
        email="mfa@example.com",
        password=PASSWORD,
        tenant=Tenant.objects.create(name="MFA test"),
        role="owner",
        is_staff=True,
    )
    DrugiSkladnik.objects.create(
        uzytkownik=user,
        sekret=totp.nowy_sekret(),
        potwierdzony_od=timezone.now(),
    )
    return user


def ticket(user):
    response = APIClient(HTTP_ORIGIN="https://panel.example.test").post(
        "/api/accounts/login/",
        {
            "username": user.username,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    return response.data["bilet"]


def finish(value, code):
    return APIClient(HTTP_ORIGIN="https://panel.example.test").post(
        "/api/accounts/login/2fa/", {"bilet": value, "kod": code}
    )


@pytest.mark.django_db
def test_password_step_does_not_create_jwt(account):
    ticket(account)
    assert OutstandingToken.objects.count() == 0


@pytest.mark.django_db
def test_ticket_is_single_use_even_with_another_backup_code(account):
    codes = dwuskladnikowe.wygeneruj_kody_zapasowe(account)
    value = ticket(account)
    assert finish(value, codes[0]).status_code == 200
    assert finish(value, codes[1]).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["inactive", "password", "factor"])
def test_ticket_invalidated_after_account_change(account, change):
    codes = dwuskladnikowe.wygeneruj_kody_zapasowe(account)
    value = ticket(account)
    if change == "inactive":
        account.is_active = False
        account.save()
    elif change == "password":
        account.set_password("Changed!Password739")
        account.save()
    else:
        factor = account.drugi_skladnik
        factor.sekret = totp.nowy_sekret()
        factor.save()
    assert finish(value, codes[0]).status_code == 401


@pytest.mark.django_db
def test_ticket_attempt_budget_cannot_be_reset_by_ip_change(account):
    codes = dwuskladnikowe.wygeneruj_kody_zapasowe(account)
    value = ticket(account)
    for index in range(5):
        assert (
            APIClient(HTTP_ORIGIN="https://panel.example.test")
            .post(
                "/api/accounts/login/2fa/",
                {"bilet": value, "kod": "invalid"},
                REMOTE_ADDR=f"198.51.100.{index}",
            )
            .status_code
            == 400
        )
    assert finish(value, codes[0]).status_code == 401


@pytest.mark.django_db
def test_secret_is_encrypted_in_database(account):
    secret = account.drugi_skladnik.sekret
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT sekret FROM accounts_drugiskladnik WHERE uzytkownik_id=%s", [account.pk]
        )
        stored = cursor.fetchone()[0]
    assert secret not in stored
    account.refresh_from_db()
    assert account.drugi_skladnik.sekret == secret


@pytest.mark.django_db
def test_admin_requires_mfa_after_password(account):
    client = Client()
    response = client.post(
        "/admin/login/?next=/admin/",
        {
            "username": account.username,
            "password": PASSWORD,
            "next": "/admin/",
        },
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_admin_rejects_an_old_password_only_session(account):
    client = Client()
    client.force_login(account)
    assert client.get("/admin/").status_code == 302
    assert client.get("/admin/accounts/customuser/").status_code == 302


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["totp", "backup"])
def test_parallel_code_consumption_has_only_one_winner(kind):
    user = CustomUser.objects.create_user(
        username="parallel",
        tenant=Tenant.objects.create(name="Parallel"),
    )
    factor = DrugiSkladnik.objects.create(
        uzytkownik=user,
        sekret=totp.nowy_sekret(),
        potwierdzony_od=timezone.now(),
    )
    code = (
        totp.kod(factor.sekret)
        if kind == "totp"
        else dwuskladnikowe.wygeneruj_kody_zapasowe(user)[0]
    )
    barrier = Barrier(2)

    def consume(_):
        close_old_connections()
        try:
            stale = DrugiSkladnik.objects.get(pk=factor.pk)
            barrier.wait(timeout=10)
            return (
                dwuskladnikowe.sprawdz_kod(stale, code)
                if kind == "totp"
                else dwuskladnikowe.zuzyj_kod_zapasowy(user, code)
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(consume, range(2))) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["totp", "backup"])
def test_admin_valid_mfa_and_revocation(account, kind):
    factor = account.drugi_skladnik
    code = (
        totp.kod(factor.sekret)
        if kind == "totp"
        else dwuskladnikowe.wygeneruj_kody_zapasowe(account)[0]
    )
    client = Client()
    response = client.post(
        "/admin/login/?next=/admin/",
        {
            "username": account.username,
            "password": PASSWORD,
            "kod": code,
            "next": "/admin/",
        },
    )
    assert response.status_code == 302
    assert response["Cache-Control"] == "no-store"
    assert client.get("/admin/").status_code == 200
    factor.delete()
    assert client.get("/admin/").status_code == 302


@pytest.mark.django_db
def test_admin_without_enrollment_cannot_login(account):
    account.drugi_skladnik.delete()
    client = Client()
    response = client.post(
        "/admin/login/",
        {
            "username": account.username,
            "password": PASSWORD,
            "kod": "123456",
        },
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@pytest.mark.parametrize("surface", ["api", "admin"])
def test_cache_failure_blocks_mfa(account, monkeypatch, surface):
    from django.core.cache import cache

    value = ticket(account)
    code = dwuskladnikowe.wygeneruj_kody_zapasowe(account)[0]

    def unavailable(*args, **kwargs):
        raise ConnectionError("synthetic cache outage")

    monkeypatch.setattr(cache, "add", unavailable)
    if surface == "api":
        assert finish(value, code).status_code == 503
    else:
        client = Client()
        response = client.post(
            "/admin/login/",
            {
                "username": account.username,
                "password": PASSWORD,
                "kod": code,
            },
        )
        assert response.status_code == 200
        assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_expiry_and_cleanup_preserve_accounts(account):
    from django.core.management import call_command

    from accounts.models import MfaChallenge

    value = ticket(account)
    code = dwuskladnikowe.wygeneruj_kody_zapasowe(account)[0]
    MfaChallenge.objects.update(expires_at=timezone.now() - timedelta(days=2))
    assert finish(value, code).status_code == 401
    call_command("purge_mfa_challenges", "--dry-run", stdout=StringIO())
    assert MfaChallenge.objects.count() == 1
    call_command("purge_mfa_challenges", stdout=StringIO())
    assert MfaChallenge.objects.count() == 0
    assert CustomUser.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
def test_jwt_failure_does_not_burn_code_or_ticket(account, monkeypatch):
    from rest_framework_simplejwt.tokens import RefreshToken

    value = ticket(account)
    code = dwuskladnikowe.wygeneruj_kody_zapasowe(account)[0]

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic token storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(RefreshToken, "for_user", fail)
        with pytest.raises(RuntimeError, match="synthetic"):
            finish(value, code)
    assert finish(value, code).status_code == 200


@pytest.mark.django_db
def test_fixture_export_is_encrypted_and_roundtrips(account):
    from django.core import serializers

    factor = account.drugi_skladnik
    serialized = serializers.serialize("json", [factor])
    assert factor.sekret not in serialized
    assert "mfa:v1:" in serialized
    for restored in serializers.deserialize("json", serialized):
        restored.save()
    assert DrugiSkladnik.objects.get(pk=factor.pk).sekret == factor.sekret


@pytest.mark.django_db
def test_key_rotation_and_missing_key_fail_closed(account, settings):
    from cryptography.fernet import InvalidToken
    from django.core.management import call_command

    from accounts.mfa_crypto import decrypt

    original_key = settings.SECRET_KEY
    secret = account.drugi_skladnik.sekret
    settings.SECRET_KEY = "synthetic-new-key-for-test-" * 3
    settings.SECRET_KEY_FALLBACKS = []
    with pytest.raises(InvalidToken):
        DrugiSkladnik.objects.get(uzytkownik=account)
    settings.SECRET_KEY_FALLBACKS = [original_key]
    call_command("rotate_mfa_secrets", "--dry-run", stdout=StringIO())
    call_command("rotate_mfa_secrets", stdout=StringIO())
    settings.SECRET_KEY_FALLBACKS = []
    assert DrugiSkladnik.objects.get(uzytkownik=account).sekret == secret
    with pytest.raises(ValueError, match="Unencrypted"):
        decrypt(secret)
    with pytest.raises(InvalidToken):
        decrypt("mfa:v1:corrupt")


@pytest.mark.django_db(transaction=True)
def test_migration_encrypts_existing_seeds_and_can_reverse():
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    old = [("accounts", "0034_pending_registration")]
    executor.migrate(old)
    apps = executor.loader.project_state(old).apps
    tenant = apps.get_model("accounts", "Tenant").objects.create(name="Legacy MFA")
    user = apps.get_model("accounts", "CustomUser").objects.create(
        username="legacy-mfa",
        tenant=tenant,
    )
    seed = totp.nowy_sekret()
    factor = apps.get_model("accounts", "DrugiSkladnik").objects.create(
        uzytkownik=user,
        sekret=seed,
        potwierdzony_od=timezone.now(),
    )
    try:
        MigrationExecutor(connection).migrate(latest)
        assert DrugiSkladnik.objects.get(pk=factor.pk).sekret == seed
        with connection.cursor() as cursor:
            cursor.execute("SELECT sekret FROM accounts_drugiskladnik WHERE id=%s", [factor.pk])
            assert seed not in cursor.fetchone()[0]
        MigrationExecutor(connection).migrate(old)
        assert apps.get_model("accounts", "DrugiSkladnik").objects.get(pk=factor.pk).sekret == seed
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True)
def test_parallel_ticket_consumption_with_distinct_codes():
    user = CustomUser.objects.create_user(
        username="parallel-ticket",
        password=PASSWORD,
        tenant=Tenant.objects.create(name="Parallel ticket"),
        role="owner",
    )
    DrugiSkladnik.objects.create(
        uzytkownik=user,
        sekret=totp.nowy_sekret(),
        potwierdzony_od=timezone.now(),
    )
    codes = dwuskladnikowe.wygeneruj_kody_zapasowe(user)
    value = ticket(user)
    barrier = Barrier(2)

    def consume(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return finish(value, codes[index]).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == [200, 401]


@pytest.mark.django_db
@pytest.mark.parametrize("code", ["١٢٣٤٥٦", "1" * 65, [], {"code": "123456"}])
def test_malformed_code_is_rejected_without_server_error(account, code):
    response = APIClient(HTTP_ORIGIN="https://panel.example.test").post(
        "/api/accounts/login/2fa/",
        {"bilet": ticket(account), "kod": code},
        format="json",
    )
    assert response.status_code == 400
