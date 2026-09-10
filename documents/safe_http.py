"""Bounded, credential-free HTTP for untrusted website source URLs.

Resolve once per hop, reject the entire answer if any address is non-public,
then connect to a numeric address. The original hostname is used for Host and
TLS verification, never for a second DNS lookup by the HTTP client.
"""

import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
import zlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPException
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

MAX_WIRE_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = 4 * 1024 * 1024
FETCH_SECONDS = 20
MAX_REDIRECTS = 3
_DNS_SLOTS = threading.BoundedSemaphore(4)
_CURRENT_BUDGET: ContextVar["CrawlBudget | None"] = ContextVar("website_fetch_budget", default=None)


class FetchError(ValueError):
    """A safe, user-visible error; never includes credentials or response content."""


class FetchLimitExceeded(FetchError):
    pass


def _remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise FetchLimitExceeded("Przekroczono czas pobierania strony.")
    return seconds


def _public_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise FetchError("Nieprawidłowy adres IP strony.") from None
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or getattr(address, "scope_id", None)
    ):
        raise FetchError("Strona musi mieć publiczny adres IP.")
    # Python 3.11 differs from newer versions on some special-use ranges.
    if isinstance(address, ipaddress.IPv4Address):
        excluded = ("192.0.0.0/24", "192.88.99.0/24")
    else:
        # Reject transition/translation addresses, including embedded private IPv4.
        excluded = (
            "::/96",
            "::ffff:0:0/96",
            "64:ff9b::/96",
            "64:ff9b:1::/48",
            "2001::/23",
            "2002::/16",
            "3fff::/20",
        )
    if any(address in ipaddress.ip_network(network) for network in excluded):
        raise FetchError("Specjalne adresy sieciowe nie są obsługiwane.")
    return address


def validate_url(url):
    """Validate without DNS (also used by serializers); return a canonical URL."""
    if not isinstance(url, str) or len(url) > 4096 or re.search(r"[\s\\\x00-\x1f\x7f]", url):
        raise FetchError("Nieprawidłowy adres strony.")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise FetchError("Nieprawidłowy adres strony.") from None
    if parsed.scheme not in {"http", "https"} or not host:
        raise FetchError("Podaj publiczny adres HTTP lub HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise FetchError("Adres strony nie może zawierać loginu ani hasła.")
    if port is not None and port not in {80, 443}:
        raise FetchError("Dozwolone są wyłącznie porty HTTP i HTTPS (80 i 443).")
    host = host.rstrip(".")
    if not host or "%" in host:
        raise FetchError("Nieprawidłowa domena strony.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        host = str(_public_address(host))
    else:
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise FetchError("Nieprawidłowa domena strony.") from None
        labels = host.split(".")
        if (
            len(host) > 253
            or len(labels) < 2
            or host.endswith((".localhost", ".local", ".internal"))
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        ):
            raise FetchError("Podaj publiczną domenę strony.")
    authority = f"[{host}]" if ":" in host else host
    default_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != default_port:
        authority += f":{port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
    return urlunsplit((parsed.scheme, authority, path, query, ""))


def same_site(url, base_url):
    """Exact canonical hostname equality, never a string prefix comparison."""
    try:
        return urlsplit(validate_url(url)).hostname == urlsplit(validate_url(base_url)).hostname
    except FetchError:
        return False


def _resolve(host, port, deadline):
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return [str(_public_address(str(literal)))]
    slots = _DNS_SLOTS
    if not slots.acquire(blocking=False):
        raise FetchLimitExceeded("Resolver DNS jest zajęty. Spróbuj ponownie później.")
    result = queue.Queue(maxsize=1)

    def lookup():
        try:
            result.put(socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM))
        except OSError as error:
            result.put(error)
        finally:
            slots.release()

    # A timed-out OS resolver may continue, but cannot block the caller or create
    # an unbounded worker queue. No resolver thread prevents process shutdown.
    threading.Thread(target=lookup, daemon=True).start()
    try:
        answer = result.get(timeout=min(5, _remaining(deadline)))
    except queue.Empty:
        raise FetchLimitExceeded("Przekroczono czas rozwiązywania domeny.") from None
    if isinstance(answer, OSError) or not answer:
        raise FetchError("Nie udało się rozwiązać domeny strony.") from None
    addresses = []
    for family, _, _, _, sockaddr in answer:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise FetchError("Nieobsługiwany adres sieciowy strony.")
        address = str(_public_address(sockaddr[0]))
        if address not in addresses:
            addresses.append(address)
    # IPv4 first also works on deployments without outbound IPv6 routing.
    return sorted(addresses, key=lambda address: ipaddress.ip_address(address).version)


@dataclass
class CrawlBudget:
    max_requests: int = 60
    max_bytes: int = 32 * 1024 * 1024
    deadline: float = field(default_factory=lambda: time.monotonic() + 120)
    requests: int = 0
    bytes: int = 0

    def request(self):
        _remaining(self.deadline)
        self.requests += 1
        if self.requests > self.max_requests:
            raise FetchLimitExceeded("Przekroczono limit żądań dla jednego źródła WWW.")

    def consume(self, count):
        self.bytes += count
        if self.bytes > self.max_bytes:
            raise FetchLimitExceeded("Przekroczono limit danych dla jednego źródła WWW.")


@contextmanager
def crawl_fetch_budget(budget=None):
    token = _CURRENT_BUDGET.set(budget or CrawlBudget())
    try:
        yield _CURRENT_BUDGET.get()
    finally:
        _CURRENT_BUDGET.reset(token)


@dataclass(frozen=True)
class Page:
    url: str
    body: bytes
    content_type: str = ""

    @property
    def text(self):
        # HTML extraction detects its own encoding; this is for robots/plain text.
        return self.body.decode("utf-8", errors="replace")


def decompress_gzip(body):
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        decoded = decoder.decompress(body, MAX_BODY_BYTES + 1)
    except zlib.error:
        raise FetchError("Nieprawidłowa odpowiedź gzip.") from None
    if len(decoded) > MAX_BODY_BYTES or decoder.unconsumed_tail:
        raise FetchLimitExceeded("Rozpakowana strona przekracza limit rozmiaru.")
    if not decoder.eof or decoder.unused_data:
        raise FetchError("Nieprawidłowa lub wieloczęściowa odpowiedź gzip.")
    return decoded


def _open_connection(parsed, address, deadline):
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection = HTTPConnection(parsed.hostname, port, timeout=min(5, _remaining(deadline)))
    # Never let http.client reconnect using the hostname after our pinned socket.
    connection.auto_open = 0
    sock = socket.create_connection((address, port), timeout=min(5, _remaining(deadline)))
    try:
        sock.settimeout(min(5, _remaining(deadline)))
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        _remaining(deadline)
        connection.sock = sock
        return connection
    except Exception:
        sock.close()
        raise


def _request(url, address, deadline, budget):
    parsed = urlsplit(url)
    connection = _open_connection(parsed, address, deadline)
    sock = connection.sock  # getresponse() may detach it for Connection: close.
    expired = threading.Event()

    def abort():
        expired.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # Already closed by the request's finally block.

    timer = threading.Timer(max(0, deadline - time.monotonic()), abort)
    timer.daemon = True
    response = None
    timer.start()
    try:
        _remaining(deadline)
        target = urlunsplit(("", "", parsed.path, parsed.query, ""))
        connection.request(
            "GET",
            target,
            headers={
                "Host": parsed.netloc,
                "User-Agent": "WebsiteSourceImporter/1.0",
                "Accept": "text/html,application/xml,text/plain,*/*;q=0.1",
                "Accept-Encoding": "gzip",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        _remaining(deadline)
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            if not location:
                raise FetchError("Przekierowanie nie zawiera adresu docelowego.")
            return location, None
        if response.status != 200:
            raise FetchError(f"Serwer strony zwrócił HTTP {response.status}.")
        length = response.getheader("Content-Length")
        if length is not None:
            try:
                size = int(length)
            except ValueError:
                raise FetchError("Nieprawidłowy rozmiar odpowiedzi strony.") from None
            if size < 0 or size > MAX_WIRE_BYTES:
                raise FetchLimitExceeded("Strona przekracza limit rozmiaru.")
        chunks, size = [], 0
        while True:
            _remaining(deadline)
            chunk = response.read(min(65536, MAX_WIRE_BYTES + 1 - size))
            size += len(chunk)
            if budget:
                budget.consume(len(chunk))
            if size > MAX_WIRE_BYTES:
                raise FetchLimitExceeded("Strona przekracza limit rozmiaru.")
            if not chunk:
                break
            chunks.append(chunk)
        if length is not None and not response.chunked and size != int(length):
            raise FetchError("Serwer przerwał pobieranie strony przed końcem odpowiedzi.")
        body = b"".join(chunks)
        encoding = response.getheader("Content-Encoding", "identity").strip().lower()
        if encoding == "gzip":
            body = decompress_gzip(body)
            if budget:
                budget.consume(max(0, len(body) - size))
        elif encoding not in {"", "identity"}:
            raise FetchError("Nieobsługiwana kompresja strony.")
        if expired.is_set():
            raise FetchLimitExceeded("Przekroczono czas pobierania strony.")
        _remaining(deadline)
        return None, Page(url, body, response.getheader("Content-Type", ""))
    finally:
        timer.cancel()
        if response is not None:
            response.close()
        connection.close()


def fetch_page(url):
    """GET public HTTP(S); all redirects share one wall-clock deadline."""
    url = validate_url(url)
    deadline = time.monotonic() + FETCH_SECONDS
    budget = _CURRENT_BUDGET.get()
    if budget:
        deadline = min(deadline, budget.deadline)
    seen = set()
    for hop in range(MAX_REDIRECTS + 1):
        if url in seen:
            raise FetchError("Pętla przekierowań strony.")
        seen.add(url)
        if budget:
            budget.request()
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = _resolve(parsed.hostname, port, deadline)
        try:
            location, page = _request(url, addresses[0], deadline, budget)
        except (OSError, HTTPException):
            raise FetchError(
                "Nie udało się bezpiecznie pobrać strony (sieć, TLS lub czas)."
            ) from None
        if page is not None:
            return page
        if hop == MAX_REDIRECTS:
            raise FetchLimitExceeded("Zbyt wiele przekierowań strony.")
        url = validate_url(urljoin(url, location))
    raise FetchError("Nie udało się pobrać strony.")  # pragma: no cover
