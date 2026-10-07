import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from django.http import StreamingHttpResponse
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from api import capacity

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def pools(monkeypatch):
    monkeypatch.setattr(capacity, "CHAT_SLOTS", threading.BoundedSemaphore(2))
    monkeypatch.setattr(capacity, "UPLOAD_SLOTS", threading.BoundedSemaphore(1))


class View(capacity.CapacityMixin, APIView):
    authentication_classes = ()
    permission_classes = ()
    throttle_classes = ()

    def get(self, request):
        return Response({"ok": True})

    def delete(self, request):
        return Response({"ok": True})

    def post(self, request):
        return StreamingHttpResponse(iter([b"first", b"last"]))


def call(view=View, method="post"):
    return view.as_view()(getattr(APIRequestFactory(), method)("/", {}, format="json"))


def test_stream_holds_slot_before_iteration_and_releases_unread_response():
    first, second = call(), call()
    try:
        denied = call()
        assert denied.status_code == 503
        assert denied.data["code"] == "server_busy"
        assert denied["Retry-After"] == "1"
        assert call(method="get").status_code == 200
        assert call(method="delete").status_code == 200
        first.close()
        replacement = call()
        assert replacement.status_code == 200
        replacement.close()
    finally:
        first.close()
        second.close()


def test_exhaustion_then_repeated_close_does_not_add_slots():
    first, second = call(), call()
    assert b"".join(first.streaming_content) == b"firstlast"
    first.close()
    first.close()
    third = call()
    try:
        assert third.status_code == 200
        assert call().status_code == 503
    finally:
        second.close()
        third.close()


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_generator_failure_releases_slot(failure):
    def broken():
        yield b"one"
        raise failure()

    class Broken(View):
        def post(self, request):
            return StreamingHttpResponse(broken())

    response = call(Broken)
    with pytest.raises(failure):
        list(response.streaming_content)
    response.close()
    a, b = call(), call()
    try:
        assert a.status_code == b.status_code == 200
    finally:
        a.close()
        b.close()


def test_raising_stream_close_still_releases():
    semaphore = threading.BoundedSemaphore(1)
    assert semaphore.acquire(False)

    class BrokenCloser:
        def __iter__(self):
            return self

        def __next__(self):
            return b"one"

        def close(self):
            raise RuntimeError("close failed")

    stream = BrokenCloser()
    wrapped = capacity.CapacityStream(stream, capacity.Lease(semaphore))
    with pytest.raises(RuntimeError):
        wrapped.close()
    assert semaphore.acquire(False)
    wrapped.close()
    assert not semaphore.acquire(False)


def test_view_exception_releases_slot():
    class Broken(View):
        def post(self, request):
            raise RuntimeError("failed before response")

    with pytest.raises(RuntimeError):
        call(Broken)
    a, b = call(), call()
    try:
        assert a.status_code == b.status_code == 200
    finally:
        a.close()
        b.close()


def test_upload_is_rejected_before_body_parser_and_chat_remains_available():
    parsed = Mock(side_effect=AssertionError("Must not read the body"))

    class Parser(JSONParser):
        def parse(self, *args, **kwargs):
            return parsed(*args, **kwargs)

    class Upload(View):
        capacity_group = "upload"
        parser_classes = [Parser]

        def post(self, request):
            return Response(request.data)

    assert capacity.UPLOAD_SLOTS.acquire(False)
    try:
        assert call(Upload).status_code == 503
        parsed.assert_not_called()
        chat = call()
        assert chat.status_code == 200
        chat.close()
    finally:
        capacity.UPLOAD_SLOTS.release()


def test_upload_slot_is_held_through_slow_storage_write():
    storing, release = threading.Event(), threading.Event()

    class Upload(View):
        capacity_group = "upload"

        def post(self, request):
            assert request.data == {}
            storing.set()
            assert release.wait(5)
            return Response({"saved": True}, status=201)

    with ThreadPoolExecutor() as executor:
        future = executor.submit(call, Upload)
        try:
            assert storing.wait(5)
            assert call(Upload).status_code == 503
            assert call(method="get").status_code == 200
        finally:
            release.set()
        assert future.result().status_code == 201
    assert call(Upload).status_code == 201


def test_competing_requests_only_admit_two_without_waiting():
    barrier = threading.Barrier(8)

    def compete(_):
        barrier.wait()
        return call()

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(compete, range(8)))
    try:
        assert sorted(r.status_code for r in responses) == [200, 200] + [503] * 6
    finally:
        for response in responses:
            response.close()


def test_all_chat_and_upload_entry_points_share_process_pools():
    from api.views.chat import ChatWithGPTView
    from api.views.chat_csv import ImportPromptLogsCSVView
    from api.views.czat_testowy import CzatTestowyView
    from api.views.documents import UploadDocumentView
    from api.views.widget import PublicChatStreamView, PublicChatView, TenantWidgetSettingsView

    for cls in (ChatWithGPTView, PublicChatView, PublicChatStreamView, CzatTestowyView):
        assert issubclass(cls, capacity.CapacityMixin)
        assert cls.capacity_group == "chat"
    for cls in (UploadDocumentView, ImportPromptLogsCSVView, TenantWidgetSettingsView):
        assert issubclass(cls, capacity.CapacityMixin)
        assert cls.capacity_group == "upload"


@pytest.mark.django_db
def test_busy_widget_does_not_create_conversation_or_charge(tenant, subscribtion, monkeypatch):
    from rest_framework.test import APIClient

    from accounts.models import MessageReservation
    from api.views import widget
    from chat.models import Conversation

    reserve = Mock(side_effect=AssertionError("Must not reserve"))
    monkeypatch.setattr(widget, "reserve_message", reserve)
    before = (Conversation.objects.count(), MessageReservation.objects.count())
    assert capacity.CHAT_SLOTS.acquire(False)
    assert capacity.CHAT_SLOTS.acquire(False)
    try:
        response = APIClient().post(
            "/api/widget/chat/stream/",
            {"message": "hello", "conversation_session_id": "cf236f5b-8082-4513-b8a5-7941f4557f10"},
            format="json",
            HTTP_X_API_KEY=str(tenant.api_key),
        )
        assert response.status_code == 503
        assert response["Retry-After"] == "1"
        reserve.assert_not_called()
        assert (Conversation.objects.count(), MessageReservation.objects.count()) == before
    finally:
        capacity.CHAT_SLOTS.release()
        capacity.CHAT_SLOTS.release()
