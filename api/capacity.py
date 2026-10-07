"""Budżet ciężkich żądań jednego procesu WSGI (Gunicorn: 1 worker, 4 threads).

Limit firmy w message_quota pilnuje rozliczeń. Tutaj pilnujemy wątków i RAM
całej usługi, wspólnie dla firm i wszystkich dróg czatu/uploadu. Nie czekamy
na semafor: oczekujący request też zajmowałby wątek potrzebny panelowi.
"""

from threading import BoundedSemaphore, Lock

from rest_framework.exceptions import APIException

CHAT_SLOTS = BoundedSemaphore(2)
UPLOAD_SLOTS = BoundedSemaphore(1)


class ServerBusy(APIException):
    status_code = 503
    default_code = "server_busy"
    wait = 1
    default_detail = {
        "detail": "Serwer obsługuje teraz inne zadania. Spróbuj ponownie za chwilę.",
        "code": "server_busy",
    }


class Lease:
    def __init__(self, semaphore):
        self.semaphore = semaphore
        self.lock = Lock()
        self.released = False

    def release(self):
        with self.lock:
            if not self.released:
                self.released = True
                self.semaphore.release()


class CapacityStream:
    """Zwalnia także nieodczytaną odpowiedź, błąd generatora i rozłączenie."""

    def __init__(self, stream, lease):
        self.stream = iter(stream)
        self.lease = lease
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        try:
            return next(self.stream)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            close = getattr(self.stream, "close", None)
            if close:
                close()
        finally:
            self.lease.release()


class CapacityMixin:
    capacity_group = "chat"

    def initial(self, request, *args, **kwargs):
        # Najpierw uwierzytelnienie, uprawnienia i throttling DRF. Żaden widok
        # nie odczytał jeszcze request.data ani nie zarezerwował wiadomości.
        super().initial(request, *args, **kwargs)
        if request.method not in {"POST", "PUT", "PATCH"}:
            return
        semaphore = CHAT_SLOTS if self.capacity_group == "chat" else UPLOAD_SLOTS
        if not semaphore.acquire(blocking=False):
            raise ServerBusy()
        self.capacity_lease = Lease(semaphore)

    def dispatch(self, request, *args, **kwargs):
        self.capacity_lease = None
        try:
            response = super().dispatch(request, *args, **kwargs)
            if self.capacity_lease is not None and response.streaming:
                # Setter StreamingHttpResponse rejestruje close(). Oryginalne
                # closery (m.in. ReservedStream) pozostają na odpowiedzi.
                response.streaming_content = CapacityStream(
                    response.streaming_content, self.capacity_lease
                )
                self.capacity_lease = None
            return response
        finally:
            if self.capacity_lease is not None:
                self.capacity_lease.release()
