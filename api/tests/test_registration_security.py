from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import CustomUser, DaneRozliczeniowe, InvitationToken, Subscription, Tenant
from api.serializers import AcceptInvitationSerializer, RegisterSerializer
from api.tests.signup_helpers import complete_registration

PASSWORD = "v7!Independent-Phrase-739"


def registration(**changes):
    return {
        "imie": "Anna",
        "nazwisko": "Nowak",
        "company_name": "Security test",
        "email": "new@example.com",
        "password": PASSWORD,
        "ulica": "Testowa 1",
        "kod_pocztowy": "00-001",
        "miasto": "Testowo",
        **changes,
    }


def invitation_data(invitation, **changes):
    return {
        "token": str(invitation.token),
        "username": "invited",
        "email": invitation.email,
        "password": PASSWORD,
        **changes,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("password", ["1", "123456789012", "password123", "AnnaNowak"])
def test_registration_rejects_weak_password_without_creating_company(password):
    response = APIClient().post("/api/accounts/register/", registration(password=password))
    assert response.status_code == 400
    assert "password" in response.data
    assert not Tenant.objects.exists()
    assert not DaneRozliczeniowe.objects.exists()


@pytest.mark.django_db
def test_password_spaces_are_preserved():
    password = "  " + PASSWORD + "  "
    response = APIClient().post("/api/accounts/register/", registration(password=password))
    response = complete_registration(response, password)
    assert response.status_code == 201
    assert CustomUser.objects.get(email="new@example.com").check_password(password)


@pytest.mark.django_db
def test_registration_normalizes_email_and_rejects_case_variant(user):
    response = APIClient().post("/api/accounts/register/", registration(email=user.email.upper()))
    assert response.status_code == 400
    response = APIClient().post("/api/accounts/register/", registration(email=" NEW@EXAMPLE.COM "))
    response = complete_registration(response, PASSWORD)
    assert response.status_code == 201
    assert CustomUser.objects.filter(email="new@example.com", username="new@example.com").exists()


@pytest.mark.django_db
def test_registration_rolls_back_billing_and_company_on_user_failure(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("synthetic user storage failure")

    monkeypatch.setattr(CustomUser.objects, "create_user", fail)
    serializer = RegisterSerializer(data=registration())
    assert serializer.is_valid(), serializer.errors
    with pytest.raises(RuntimeError):
        serializer.save()
    assert not Tenant.objects.exists()
    assert not DaneRozliczeniowe.objects.exists()


@pytest.mark.django_db
def test_invitation_requires_matching_email_and_strong_password(tenant):
    invite = InvitationToken.objects.create(tenant=tenant, email="recipient@example.com")
    client = APIClient()
    for changes, field in [
        ({"email": "other@example.com"}, "email"),
        ({"password": "1"}, "password"),
    ]:
        response = client.post("/api/accounts/accept-invite/", invitation_data(invite, **changes))
        assert response.status_code == 400
        assert field in response.data
    invite.refresh_from_db()
    assert invite.users == 0
    assert not CustomUser.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_invitation_matching_is_case_insensitive(tenant):
    invite = InvitationToken.objects.create(tenant=tenant, email="Recipient@Example.com")
    response = APIClient().post(
        "/api/accounts/accept-invite/", invitation_data(invite, email="RECIPIENT@EXAMPLE.COM")
    )
    assert response.status_code == 201
    assert CustomUser.objects.filter(email="recipient@example.com").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["used", "expired", "revoked"])
def test_invitation_is_rechecked_at_save(tenant, change):
    invite = InvitationToken.objects.create(tenant=tenant, email="recipient@example.com")
    serializer = AcceptInvitationSerializer(data=invitation_data(invite))
    assert serializer.is_valid(), serializer.errors
    if change == "revoked":
        invite.delete()
    elif change == "used":
        InvitationToken.objects.filter(pk=invite.pk).update(users=1)
    else:
        InvitationToken.objects.filter(pk=invite.pk).update(
            created_at=timezone.now() - timedelta(days=5)
        )
    with pytest.raises(ValidationError):
        serializer.save()
    assert not CustomUser.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_database_rejects_duplicate_email_case_insensitively(user, tenant):
    with pytest.raises(IntegrityError), transaction.atomic():
        CustomUser.objects.create_user(
            username="different", email=user.email.upper(), tenant=tenant
        )


@pytest.mark.django_db
def test_registration_limit_applies_without_tenant_or_widget_key():
    responses = [
        APIClient().post("/api/accounts/register/", {}, REMOTE_ADDR="198.51.100.10")
        for _ in range(6)
    ]
    assert [r.status_code for r in responses] == [400] * 5 + [429]
    assert "Retry-After" in responses[-1]


@pytest.mark.django_db(transaction=True)
def test_parallel_registrations_create_only_one_company():
    barrier = Barrier(2)

    def create(index):
        close_old_connections()
        try:
            serializer = RegisterSerializer(
                data=registration(email=["Case@Example.com", "case@example.com"][index])
            )
            assert serializer.is_valid(), serializer.errors
            barrier.wait(timeout=10)
            try:
                serializer.save()
                return 201
            except ValidationError:
                return 400
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert sorted(results) == [201, 400]
    assert (
        CustomUser.objects.count()
        == Tenant.objects.count()
        == DaneRozliczeniowe.objects.count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("same_token", [True, False])
def test_parallel_invitation_acceptance_respects_token_and_last_seat(same_token):
    tenant = Tenant.objects.create(name="Concurrent registration")
    for i in range(2):
        CustomUser.objects.create_user(
            username=f"existing-{i}", email=f"existing-{i}@example.com", tenant=tenant
        )
    Subscription.objects.create(
        tenant=tenant,
        plan_type="grow",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=30),
    )
    first = InvitationToken.objects.create(tenant=tenant, email="one@example.com")
    second = (
        first
        if same_token
        else InvitationToken.objects.create(tenant=tenant, email="two@example.com")
    )
    barrier = Barrier(2)

    def accept(index):
        close_old_connections()
        try:
            serializer = AcceptInvitationSerializer(
                data=invitation_data([first, second][index], username=f"new-{index}")
            )
            assert serializer.is_valid(), serializer.errors
            barrier.wait(timeout=10)
            try:
                serializer.save()
                return 201
            except ValidationError:
                return 400
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, range(2)))
    assert sorted(results) == [201, 400]
    assert tenant.users.count() == 3
    assert sum(InvitationToken.objects.values_list("users", flat=True)) == 1


@pytest.mark.django_db
def test_duplicate_username_does_not_consume_invitation(user, tenant):
    invite = InvitationToken.objects.create(tenant=tenant, email="recipient@example.com")
    response = APIClient().post(
        "/api/accounts/accept-invite/", invitation_data(invite, username=user.username)
    )
    assert response.status_code == 400
    invite.refresh_from_db()
    assert invite.users == 0
    assert not CustomUser.objects.filter(email=invite.email).exists()


@pytest.mark.django_db
def test_failed_trial_creation_rolls_back_whole_registration(monkeypatch):
    def fail(*args):
        raise RuntimeError("synthetic subscription failure")

    monkeypatch.setattr("api.views.activation.zalozenie_okresu_probnego", fail)
    with pytest.raises(RuntimeError):
        complete_registration(APIClient().post("/api/accounts/register/", registration()), PASSWORD)
    assert not CustomUser.objects.exists()
    assert not Tenant.objects.exists()
    assert not DaneRozliczeniowe.objects.exists()


@pytest.mark.django_db
def test_email_change_cannot_create_case_duplicate(user, tenant):
    user.role = "owner"
    user.save()
    other = CustomUser.objects.create_user(
        username="second", email="second@example.com", tenant=tenant
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    response = client.patch(f"/api/users/{other.pk}/", {"email": user.email.upper()}, format="json")
    assert response.status_code == 400
    other.refresh_from_db()
    assert other.email == "second@example.com"


@pytest.mark.django_db
def test_blank_legacy_emails_remain_allowed(tenant):
    for username in ("legacy-one", "legacy-two"):
        CustomUser.objects.create_user(username=username, tenant=tenant)
    assert CustomUser.objects.count() == 2


@pytest.mark.django_db
def test_legacy_multiple_use_invitation_is_closed_after_first_acceptance(tenant):
    invite = InvitationToken.objects.create(
        tenant=tenant, email="recipient@example.com", max_users=10, users=1
    )
    assert not invite.is_valid()
    response = APIClient().post("/api/accounts/accept-invite/", invitation_data(invite))
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("maximum", [0, 2, 100])
def test_new_invitation_is_always_for_one_recipient(user, maximum):
    user.role = "owner"
    user.save()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    response = client.post(
        "/api/accounts/invitations/", {"email": "recipient@example.com", "max_users": maximum}
    )
    assert response.status_code == 400
    assert not InvitationToken.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes", [{"password": "p" * 1025}, {"email": "a" * 140 + "@example.com"}]
)
def test_oversized_credentials_are_rejected(changes):
    response = APIClient().post("/api/accounts/register/", registration(**changes))
    assert response.status_code == 400
    assert not Tenant.objects.exists()


@pytest.mark.django_db
def test_cache_failure_does_not_bypass_signup_limit(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("synthetic cache outage")

    monkeypatch.setattr("api.registration_throttles.cache.add", fail)
    response = APIClient().post("/api/accounts/register/", registration())
    assert response.status_code == 503
    assert not Tenant.objects.exists()


def test_parallel_rate_limit_is_atomic(monkeypatch):
    from rest_framework.test import APIRequestFactory

    from api.registration_throttles import RegistrationThrottle

    monkeypatch.setattr("api.registration_throttles.time.time", lambda: 3601)
    barrier = Barrier(10)

    def attempt(_):
        request = APIRequestFactory().post("/", REMOTE_ADDR="198.51.100.10")
        barrier.wait(timeout=10)
        return RegistrationThrottle().allow_request(request, None)

    with ThreadPoolExecutor(max_workers=10) as pool:
        assert sum(pool.map(attempt, range(10))) == 5


def test_distributed_signups_hit_global_limit(monkeypatch):
    from rest_framework.test import APIRequestFactory

    from api.registration_throttles import RegistrationThrottle

    monkeypatch.setattr("api.registration_throttles.time.time", lambda: 3601)
    outcomes = []
    for index in range(31):
        request = APIRequestFactory().post("/", REMOTE_ADDR=f"198.51.100.{index}")
        outcomes.append(RegistrationThrottle().allow_request(request, None))
    assert outcomes == [True] * 30 + [False]


@pytest.mark.django_db
def test_missing_shared_production_cache_disables_signup(settings):
    settings.USE_SHARED_CACHE = False
    response = APIClient().post("/api/accounts/register/", registration())
    assert response.status_code == 503
    assert not Tenant.objects.exists()


def test_unrelated_database_errors_are_not_reported_as_duplicate_email():
    from accounts.registration import account_conflict

    error = IntegrityError("synthetic unrelated storage failure")
    with pytest.raises(IntegrityError) as raised:
        account_conflict(error)
    assert raised.value is error


@pytest.mark.django_db(transaction=True)
def test_migration_refuses_ambiguous_emails_without_deleting_accounts():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    old_target = [("accounts", "0032_message_reservations")]
    new_target = [("accounts", "0033_unique_account_email")]
    executor.migrate(old_target)
    old_apps = executor.loader.project_state(old_target).apps
    User = old_apps.get_model("accounts", "CustomUser")
    Company = old_apps.get_model("accounts", "Tenant")
    tenant = Company.objects.create(name="Migration test")
    first = User.objects.create(username="migration-one", email="Case@Example.com", tenant=tenant)
    second = User.objects.create(
        username="migration-two", email=" case@example.com ", tenant=tenant
    )
    try:
        with pytest.raises(RuntimeError, match="1 conflicting groups"):
            MigrationExecutor(connection).migrate(new_target)
        assert User.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    finally:
        second.delete()
        MigrationExecutor(connection).migrate(latest_targets)


@pytest.mark.django_db(transaction=True)
def test_invitation_and_direct_creation_share_last_seat(monkeypatch):
    from api.views.users import UserViewSet

    tenant = Tenant.objects.create(name="Mixed account creation")
    owner = CustomUser.objects.create_user(
        username="owner", email="owner@example.com", tenant=tenant, role="owner"
    )
    CustomUser.objects.create_user(username="existing", email="existing@example.com", tenant=tenant)
    Subscription.objects.create(
        tenant=tenant,
        plan_type="grow",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=30),
    )
    invite = InvitationToken.objects.create(tenant=tenant, email="recipient@example.com")
    barrier = Barrier(2)
    original_create = AcceptInvitationSerializer.create
    original_lock = UserViewSet._lock_team

    def accept_after_barrier(serializer, data):
        barrier.wait(timeout=10)
        return original_create(serializer, data)

    def lock_after_barrier(view):
        barrier.wait(timeout=10)
        return original_lock(view)

    monkeypatch.setattr(AcceptInvitationSerializer, "create", accept_after_barrier)
    monkeypatch.setattr(UserViewSet, "_lock_team", lock_after_barrier)
    access = str(AccessToken.for_user(owner))

    def create(index):
        close_old_connections()
        try:
            client = APIClient()
            if index:
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
                return client.post(
                    "/api/users/",
                    {"username": "direct", "email": "direct@example.com", "role": "employee"},
                    format="json",
                ).status_code
            return client.post(
                "/api/accounts/accept-invite/", invitation_data(invite), format="json"
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert sorted(results) == [201, 400]
    assert tenant.users.count() == 3
