"""Regresja F01–F03: prawdziwy JWT, dwa tenanty i publiczne klucze widgetu."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from accounts.models import CustomUser, InvitationToken, Subscription, Tenant, WpisDziennika
from api.session_tokens import SessionRefreshToken
from api.throttles import APIKeyRateThrottle, SubscriptionRateThrottle
from api.views.chat_csv import ExportPromptLogsCSVView, ImportPromptLogsCSVView
from api.views.documents import DocumentsViewSet
from api.views.users import UserViewSet
from chat.models import FAQ, Conversation, PromptLog
from documents.models import Document

pytestmark = pytest.mark.django_db


@pytest.fixture
def firmy():
    a = Tenant.objects.create(name="Firma A")
    b = Tenant.objects.create(name="Firma B")
    for tenant in (a, b):
        Subscription.objects.create(
            tenant=tenant,
            plan_type="pro",
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=30),
        )
    accounts = {
        role: CustomUser.objects.create_user(username=f"a-{role}", tenant=a, role=role)
        for role in ("owner", "employee", "viewer")
    }
    owner_b = CustomUser.objects.create_user(username="b-owner", tenant=b, role="owner")
    documents = [Document.objects.create(tenant=t, name=t.name, content=t.name) for t in (a, b)]
    faqs = [FAQ.objects.create(tenant=t, question=t.name, answer=t.name) for t in (a, b)]
    for tenant in (a, b):
        conversation = Conversation.objects.create(tenant=tenant, user_identifier=tenant.name)
        PromptLog.objects.create(
            tenant=tenant,
            conversation=conversation,
            prompt=tenant.name,
            response=tenant.name,
            tokens=0,
            source="faq",
            model="test",
        )
        InvitationToken.objects.create(tenant=tenant, email=f"invite-{tenant.pk}@example.test")
    return SimpleNamespace(a=a, b=b, users=accounts, owner_b=owner_b, docs=documents, faqs=faqs)


def klient(user, key=None):
    client = APIClient()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {SessionRefreshToken.for_user(user).access_token}"}
    if key is not None:
        headers["HTTP_X_API_KEY"] = str(key)
    client.credentials(**headers)
    return client


@pytest.mark.parametrize("role", ["owner", "employee", "viewer"])
@pytest.mark.parametrize("key_kind", ["none", "own", "other", "malformed"])
@pytest.mark.parametrize(
    "endpoint",
    [
        "documents",
        "document",
        "faq",
        "users",
        "chat/logs",
        "accounts/invitations/list",
    ],
)
def test_read_boundaries(firmy, role, key_kind, endpoint):
    key = {
        "none": None,
        "own": firmy.a.api_key,
        "other": firmy.b.api_key,
        "malformed": "not-a-uuid",
    }[key_kind]
    path = f"/api/{endpoint}/" if endpoint != "document" else f"/api/documents/{firmy.docs[0].pk}/"
    response = klient(firmy.users[role], key).get(path)
    allowed = key_kind in ("none", "own")
    if endpoint == "users":
        allowed = allowed and role in ("owner", "employee")
    elif endpoint == "accounts/invitations/list":
        allowed = allowed and role == "owner"
    assert response.status_code == (200 if allowed else 403)
    if allowed:
        assert "Firma B" not in response.content.decode()
        assert "b-owner" not in response.content.decode()


@pytest.mark.parametrize("resource", ["documents", "faq", "users"])
def test_foreign_object_is_not_found_with_own_identity(firmy, resource):
    pk = {"documents": firmy.docs[1].pk, "faq": firmy.faqs[1].pk, "users": firmy.owner_b.pk}[
        resource
    ]
    assert klient(firmy.users["owner"]).get(f"/api/{resource}/{pk}/").status_code == 404


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_foreign_key_cannot_write_foreign_faq(firmy, method):
    client = klient(firmy.users["owner"], firmy.b.api_key)
    response = getattr(client, method)(
        f"/api/faq/{firmy.faqs[1].pk}/",
        {"question": "changed", "answer": "changed"},
        format="json",
    )
    assert response.status_code == 403
    firmy.faqs[1].refresh_from_db()
    assert firmy.faqs[1].answer == "Firma B"


def test_foreign_key_cannot_create_records(firmy):
    response = klient(firmy.users["owner"], firmy.b.api_key).post(
        "/api/faq/",
        {"question": "injected", "answer": "injected"},
        format="json",
    )
    assert response.status_code == 403
    assert not FAQ.objects.filter(question="injected").exists()


@pytest.mark.parametrize("path", ["/api/documents/", "/api/users/", "/api/chat/export/"])
def test_public_key_does_not_authenticate_panel(firmy, path):
    response = APIClient().get(path, HTTP_X_API_KEY=str(firmy.b.api_key))
    assert response.status_code == 401


@pytest.mark.parametrize("token_kind", ["invalid", "expired"])
def test_invalid_jwt_cannot_fall_back_to_public_key(firmy, token_kind):
    token = SessionRefreshToken.for_user(firmy.users["owner"]).access_token
    token.set_exp(lifetime=timedelta(seconds=-1))
    response = APIClient().get(
        "/api/widget-settings/",
        HTTP_X_API_KEY=str(firmy.a.api_key),
        HTTP_AUTHORIZATION=f"Bearer {token if token_kind == 'expired' else 'invalid'}",
    )
    assert response.status_code == 401


def test_public_widget_still_works_without_jwt(firmy):
    assert (
        APIClient()
        .get(
            "/api/widget-settings/",
            HTTP_X_API_KEY=str(firmy.b.api_key),
        )
        .status_code
        == 200
    )


def test_malformed_public_key_is_a_client_error():
    response = APIClient().get("/api/widget-settings/", HTTP_X_API_KEY="not-a-uuid")
    assert response.status_code == 401


@pytest.mark.parametrize("role", ["employee", "viewer"])
@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_non_owner_cannot_change_users(firmy, role, method):
    user = firmy.users[role]
    response = getattr(klient(user), method)(
        f"/api/users/{user.pk}/",
        {"username": user.username, "role": "owner"},
        format="json",
    )
    assert response.status_code == 403
    user.refresh_from_db()
    assert user.role == role


@pytest.mark.parametrize("change", ["deactivate", "demote", "delete"])
def test_last_active_owner_is_protected(firmy, change):
    # Nieaktywny właściciel nie jest zastępstwem, które zachowuje dostęp do firmy.
    CustomUser.objects.create_user(
        username="inactive-owner", tenant=firmy.a, role="owner", is_active=False
    )
    owner = firmy.users["owner"]
    client = klient(owner)
    if change == "delete":
        response = client.delete(f"/api/users/{owner.pk}/")
    else:
        payload = {"is_active": False} if change == "deactivate" else {"role": "viewer"}
        response = client.patch(f"/api/users/{owner.pk}/", payload, format="json")
    assert response.status_code == 400
    owner.refresh_from_db()
    assert owner.role == "owner" and owner.is_active


def test_owner_can_manage_own_team_without_assigning_another_tenant(firmy):
    user = firmy.users["employee"]
    response = klient(firmy.users["owner"]).patch(
        f"/api/users/{user.pk}/",
        {"role": "owner", "tenant": firmy.b.pk},
        format="json",
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.role == "owner" and user.tenant_id == firmy.a.pk
    response = klient(user).delete(f"/api/users/{firmy.users['owner'].pk}/")
    assert response.status_code == 204
    assert CustomUser.objects.filter(tenant=firmy.a, role="owner", is_active=True).exists()


def test_direct_user_creation_cannot_bypass_seat_limit(firmy):
    Subscription.objects.filter(tenant=firmy.a).update(plan_type="start")
    response = klient(firmy.users["owner"]).post(
        "/api/users/",
        {"username": "over-limit", "role": "employee"},
        format="json",
    )
    assert response.status_code == 400
    assert not CustomUser.objects.filter(username="over-limit").exists()


@pytest.mark.parametrize("key_kind", ["none", "own", "other"])
@pytest.mark.parametrize("operation", ["demote", "deactivate", "delete"])
def test_foreign_user_cannot_be_modified(firmy, key_kind, operation):
    key = {"none": None, "own": firmy.a.api_key, "other": firmy.b.api_key}[key_kind]
    client = klient(firmy.users["owner"], key)
    path = f"/api/users/{firmy.owner_b.pk}/"
    if operation == "delete":
        response = client.delete(path)
    else:
        payload = {"role": "viewer"} if operation == "demote" else {"is_active": False}
        response = client.patch(path, payload, format="json")
    assert response.status_code == (403 if key_kind == "other" else 404)
    firmy.owner_b.refresh_from_db()
    assert firmy.owner_b.role == "owner" and firmy.owner_b.is_active


def test_owner_can_delete_self_when_another_owner_remains(firmy):
    replacement = firmy.users["employee"]
    replacement.role = "owner"
    replacement.save(update_fields=["role"])
    owner = firmy.users["owner"]
    pk = owner.pk
    response = klient(owner).delete(f"/api/users/{pk}/")
    assert response.status_code == 204
    assert not CustomUser.objects.filter(pk=pk).exists()
    entry = WpisDziennika.objects.get(sciezka=f"/api/users/{pk}/", metoda="DELETE")
    assert entry.uzytkownik_id is None
    assert entry.nazwa_uzytkownika == owner.username


@pytest.mark.parametrize("throttle_class", [APIKeyRateThrottle, SubscriptionRateThrottle])
def test_throttle_rejects_substituted_context(firmy, throttle_class):
    request = APIRequestFactory().get("/api/documents/", HTTP_X_API_KEY=str(firmy.b.api_key))
    request.user = firmy.users["owner"]
    request.tenant = firmy.b
    with pytest.raises(PermissionDenied):
        throttle_class().get_cache_key(request, None)
    assert request.tenant == firmy.b  # Odmowa nie podmienia po cichu firmy.


def test_queryset_rejects_substituted_context_without_other_guards(firmy):
    request = APIRequestFactory().get("/api/documents/")
    request.tenant = firmy.b
    force_authenticate(request, user=firmy.users["owner"])
    response = DocumentsViewSet.as_view(
        {"get": "list"}, permission_classes=[], throttle_classes=[]
    )(request)
    assert response.status_code == 403


@pytest.mark.parametrize("throttle_class", [APIKeyRateThrottle, SubscriptionRateThrottle])
def test_throttle_never_resolves_tenant_from_header(firmy, throttle_class):
    request = APIRequestFactory().get("/api/documents/", HTTP_X_API_KEY=str(firmy.b.api_key))
    throttle = throttle_class()
    assert throttle.get_cache_key(request, None) is None
    assert not hasattr(request, "tenant")
    assert not hasattr(request, "subscription")


@pytest.mark.parametrize("operation", ["import", "export"])
@pytest.mark.parametrize("key_kind", ["none", "own", "other"])
def test_csv_uses_authenticated_tenant_even_without_middleware(firmy, operation, key_kind):
    # Bez middleware/throttli: osobny dowód, że CSV nie wybiera firmy z klucza.
    user = firmy.users["owner"]
    key = {"none": None, "own": firmy.a.api_key, "other": firmy.b.api_key}[key_kind]
    headers = {"HTTP_X_API_KEY": str(key)} if key else {}
    factory = APIRequestFactory()
    if operation == "export":
        request = factory.get("/api/chat/export/", **headers)
        view = ExportPromptLogsCSVView
    else:
        upload = SimpleUploadedFile("history.csv", b"prompt,response\nnew,reply\n")
        request = factory.post("/api/chat/import/", {"file": upload}, format="multipart", **headers)
        view = ImportPromptLogsCSVView
    request.tenant = firmy.a
    force_authenticate(request, user=user)
    response = view.as_view(throttle_classes=[])(request)
    if key_kind == "other":
        assert response.status_code == 403
    else:
        assert response.status_code == (200 if operation == "export" else 201)
        if operation == "export":
            assert "Firma A" in response.content.decode()
            assert "Firma B" not in response.content.decode()
        else:
            assert PromptLog.objects.filter(tenant=firmy.a, prompt="new").exists()
    assert not PromptLog.objects.filter(tenant=firmy.b, prompt="new").exists()


def test_csv_round_trip_works_with_jwt_alone(firmy):
    client = klient(firmy.users["owner"])
    upload = SimpleUploadedFile("history.csv", b"prompt,response\nround-trip,reply\n")
    assert client.post("/api/chat/import/", {"file": upload}, format="multipart").status_code == 201
    response = client.get("/api/chat/export/")
    assert response.status_code == 200
    assert "round-trip" in response.content.decode()
    assert "Firma B" not in response.content.decode()


@pytest.mark.django_db(transaction=True)
def test_parallel_owner_demotions_leave_one_active_owner():
    tenant = Tenant.objects.create(name="Concurrent owners")
    owners = [
        CustomUser.objects.create_user(username=f"owner-{i}", tenant=tenant, role="owner")
        for i in range(2)
    ]
    barrier = Barrier(2)

    def demote(owner):
        close_old_connections()
        try:
            client = klient(owner)
            barrier.wait(timeout=10)
            return client.patch(
                f"/api/users/{owner.pk}/", {"role": "viewer"}, format="json"
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(demote, owners))
    assert sorted(statuses) == [200, 400]
    assert CustomUser.objects.filter(tenant=tenant, role="owner", is_active=True).count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["delete", "demote", "deactivate"])
def test_owner_permissions_are_rechecked_after_waiting_for_lock(monkeypatch, operation):
    tenant = Tenant.objects.create(name="Concurrent access changes")
    owners = [
        CustomUser.objects.create_user(username=f"concurrent-{i}", tenant=tenant, role="owner")
        for i in range(2)
    ]
    barrier = Barrier(2)
    original_lock = UserViewSet._lock_team

    def lock_after_both_requests_pass_permissions(view):
        barrier.wait(timeout=10)
        return original_lock(view)

    monkeypatch.setattr(UserViewSet, "_lock_team", lock_after_both_requests_pass_permissions)

    def change_other_owner(index):
        close_old_connections()
        try:
            client = klient(owners[index])
            path = f"/api/users/{owners[1 - index].pk}/"
            if operation == "delete":
                return client.delete(path).status_code
            payload = {"role": "viewer"} if operation == "demote" else {"is_active": False}
            return client.patch(path, payload, format="json").status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(change_other_owner, range(2)))
    assert sorted(statuses) == [204 if operation == "delete" else 200, 403]
    assert CustomUser.objects.filter(tenant=tenant, role="owner", is_active=True).count() == 1
