"""Budżet ciężkich żądań jednego procesu WSGI (Gunicorn: 1 worker gthread).

Limit firmy w message_quota pilnuje rozliczeń. Tutaj pilnujemy wątków i RAM
całej usługi, wspólnie dla wszystkich dróg czatu/uploadu. Nie czekamy na
wolne miejsce: oczekujący request też zajmowałby wątek potrzebny panelowi.

Pula ma też limit na jedną firmę. Bez niego jedna firma z ruchem - albo ktoś,
kto przez publiczny klucz widgetu trzyma kilka długich rozmów - zajmowała
wszystkie miejsca, a widgety pozostałych klientów odmawiały.
"""

import logging
from threading import Lock

from django.conf import settings
from rest_framework.exceptions import APIException

from accounts.odmowy import PowodOdmowy, zapisz_odmowe

logger = logging.getLogger(__name__)


class Pula:
    """Miejsca na ciężkie żądania w procesie: łącznie i dla jednej firmy."""

    def __init__(self, razem, na_firme):
        self.razem = razem
        self.na_firme = na_firme
        self.zajete = 0
        self.firmy = {}
        self.lock = Lock()

    def zajmij(self, firma):
        """None, gdy miejsce zajęte; inaczej powód odmowy."""
        with self.lock:
            if self.zajete >= self.razem:
                return PowodOdmowy.SERWER_ZAJETY
            if self.firmy.get(firma, 0) >= self.na_firme:
                return PowodOdmowy.LIMIT_ROZMOW_FIRMY
            self.zajete += 1
            self.firmy[firma] = self.firmy.get(firma, 0) + 1
            return None

    def zwolnij(self, firma):
        with self.lock:
            self.zajete -= 1
            if self.firmy[firma] > 1:
                self.firmy[firma] -= 1
            else:
                del self.firmy[firma]


CHAT_SLOTS = Pula(settings.POJEMNOSC_ROZMOW, settings.POJEMNOSC_ROZMOW_FIRMY)
UPLOAD_SLOTS = Pula(settings.POJEMNOSC_UPLOADOW, settings.POJEMNOSC_UPLOADOW)


class ServerBusy(APIException):
    status_code = 503
    default_code = "server_busy"
    wait = 1
    default_detail = {
        "detail": "Serwer obsługuje teraz inne zadania. Spróbuj ponownie za chwilę.",
        "code": "server_busy",
    }


class Lease:
    def __init__(self, pula, firma):
        self.pula = pula
        self.firma = firma
        self.lock = Lock()
        self.released = False

    def release(self):
        with self.lock:
            if not self.released:
                self.released = True
                self.pula.zwolnij(self.firma)


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

    def wymaga_miejsca(self, request):
        """Czy to żądanie zajmuje miejsce. Widok może zwolnić lekkie zapisy."""
        return True

    def initial(self, request, *args, **kwargs):
        # Najpierw uwierzytelnienie, uprawnienia i throttling DRF. Żaden widok
        # nie odczytał jeszcze request.data ani nie zarezerwował wiadomości.
        super().initial(request, *args, **kwargs)
        if request.method not in {"POST", "PUT", "PATCH"} or not self.wymaga_miejsca(request):
            return
        pula = CHAT_SLOTS if self.capacity_group == "chat" else UPLOAD_SLOTS
        # Firma jest już ustalona i sprawdzona przez uwierzytelnienie
        # i uprawnienia: klucz widgetu albo konto panelu.
        tenant = getattr(request, "tenant", None)
        firma = tenant.pk if tenant is not None else None
        powod = pula.zajmij(firma)
        if powod is not None:
            self._zapisz_odmowe(tenant, powod)
            raise ServerBusy()
        self.capacity_lease = Lease(pula, firma)

    def _zapisz_odmowe(self, tenant, powod):
        # Liczymy tylko rozmowy: upload to panel, którego użytkownik widzi
        # komunikat od razu. Licznik nie może zamienić 503 w 500.
        if self.capacity_group != "chat":
            return
        logger.warning("Brak miejsca na rozmowę: %s, firma %s", powod, getattr(tenant, "pk", None))
        try:
            zapisz_odmowe(tenant, powod)
        except Exception:
            logger.exception("Nie udało się zapisać odmowy z braku miejsca")

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
