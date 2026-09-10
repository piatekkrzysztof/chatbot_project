import gzip
import io
import socket
import ssl
import threading
import time
from unittest.mock import Mock

import pytest

from documents import safe_http as http

PUBLIC = "93.184.216.34"
PUBLIC_V6 = "2606:4700:4700::1111"


def dns_answer(*addresses):
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
        for ip in addresses
    ]


class WireSocket:
    """Runs the real http.client parser over synthetic bytes, without network."""

    def __init__(self, data):
        self.data = data
        self.sent = b""
        self.closed = False

    def settimeout(self, timeout):
        assert 0 < timeout <= 5

    def sendall(self, data):
        self.sent += data

    def makefile(self, *args):
        return io.BytesIO(self.data)

    def close(self):
        self.closed = True

    def shutdown(self, how):
        self.closed = True


@pytest.fixture
def network(monkeypatch):
    resolver = Mock(return_value=dns_answer(PUBLIC))
    monkeypatch.setattr(http.socket, "getaddrinfo", resolver)
    wires = []
    connect = Mock()

    def install(*responses):
        wires.extend(WireSocket(response) for response in responses)
        connect.side_effect = wires
        monkeypatch.setattr(http.socket, "create_connection", connect)
        return resolver, connect, wires

    return install


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "0.0.0.0",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "192.0.0.9",
        "192.88.99.2",
        "198.18.0.1",
        "192.0.2.1",
        "255.255.255.255",
        "::1",
        "::",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
        "2001:db8::1",
        "3fff::1",
    ],
)
def test_rejects_every_non_public_dns_answer(address, network):
    resolver, connect, _ = network()
    resolver.return_value = dns_answer(PUBLIC, address)
    with pytest.raises(http.FetchError):
        http.fetch_page("http://example.com/")
    connect.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "https://u:p@example.com/",
        "http://localhost/",
        "http://host.local/",
        "http://host.internal/",
        "http://host/",
        "http://example.com:22/",
        "http://example.com:bad/",
        "http://[::1]/",
        "http://[fe80::1%25eth0]/",
        "http://example.com\\@127.0.0.1/",
        "http://example.com/\r\nHost:evil",
        "http://example.com/%0d\n",
        "http://bad_host.com/",
        "http://%31%32%37.0.0.1/",
        "http://example..com/",
        "http://[not-an-ip]/",
    ],
)
def test_rejects_ambiguous_url_before_dns(url, network):
    resolver, connect, _ = network()
    with pytest.raises(http.FetchError):
        http.fetch_page(url)
    resolver.assert_not_called()
    connect.assert_not_called()


@pytest.mark.parametrize("host", ["2130706433", "0177.0.0.1", "0x7f.0.0.1"])
def test_legacy_ipv4_spelling_cannot_bypass_dns_policy(host, network):
    resolver, connect, _ = network()
    resolver.return_value = dns_answer("127.0.0.1")
    with pytest.raises(http.FetchError):
        http.fetch_page(f"http://{host}/")
    connect.assert_not_called()


def test_dns_is_pinned_even_when_next_lookup_would_rebind(network):
    resolver, connect, wires = network(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    resolver.side_effect = [dns_answer(PUBLIC), dns_answer("127.0.0.1")]
    result = http.fetch_page("http://example.com/path?q=1")
    assert result.body == b"OK"
    assert resolver.call_count == 1
    assert connect.call_args.args == ((PUBLIC, 80),)
    assert b"GET /path?q=1 HTTP/1.1\r\n" in wires[0].sent
    assert b"Host: example.com\r\n" in wires[0].sent
    assert wires[0].closed


def test_proxy_and_netrc_environment_cannot_inject_credentials(network, monkeypatch):
    _, connect, wires = network(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy-user:proxy-pass@127.0.0.1:8888")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setenv("NETRC", "must-not-read-this-file")
    assert http.fetch_page("http://example.com/").body == b"OK"
    assert connect.call_args.args == ((PUBLIC, 80),)
    assert b"Authorization" not in wires[0].sent
    assert b"Cookie" not in wires[0].sent


def test_redirect_loop_stops_without_second_request(network):
    _, connect, _ = network(b"HTTP/1.1 302 Found\r\nLocation: /#same\r\n\r\n")
    with pytest.raises(http.FetchError, match="Pętla"):
        http.fetch_page("http://example.com/")
    assert connect.call_count == 1


@pytest.mark.parametrize("answer", [[], socket.gaierror("synthetic resolver error")])
def test_failed_dns_never_connects(answer, network):
    resolver, connect, _ = network()
    if isinstance(answer, Exception):
        resolver.side_effect = answer
    else:
        resolver.return_value = answer
    with pytest.raises(http.FetchError, match="domeny"):
        http.fetch_page("http://example.com/")
    connect.assert_not_called()


def test_https_preserves_hostname_and_certificate_validation(network, monkeypatch):
    _, connect, wires = network(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    context = ssl.create_default_context()
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    wrap = Mock(return_value=wires[0])
    monkeypatch.setattr(context, "wrap_socket", wrap)
    monkeypatch.setattr(http.ssl, "create_default_context", lambda: context)
    assert http.fetch_page("https://EXAMPLE.com./").body == b"OK"
    assert connect.call_args.args == ((PUBLIC, 443),)
    wrap.assert_called_once_with(wires[0], server_hostname="example.com")


def test_tls_failure_is_closed_and_never_retried_as_plain_http(network, monkeypatch):
    _, connect, wires = network(b"")
    context = Mock()
    context.wrap_socket.side_effect = ssl.SSLCertVerificationError("synthetic-secret")
    monkeypatch.setattr(http.ssl, "create_default_context", lambda: context)
    with pytest.raises(http.FetchError) as error:
        http.fetch_page("https://example.com/")
    assert "synthetic-secret" not in str(error.value)
    assert wires[0].closed
    assert connect.call_count == 1


def test_literal_ipv6_has_bracketed_host_and_no_dns(network):
    resolver, connect, wires = network(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    assert http.fetch_page(f"http://[{PUBLIC_V6}]/").body == b"OK"
    resolver.assert_not_called()
    assert connect.call_args.args == ((PUBLIC_V6, 80),)
    assert f"Host: [{PUBLIC_V6}]\r\n".encode() in wires[0].sent


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "file:///etc/passwd",
        "http://u:p@example.com/",
        "http://example.com:6379/",
        "http://private.example.com/",
    ],
)
def test_redirect_cannot_reach_private_or_unsafe_target(location, network):
    resolver, connect, _ = network(f"HTTP/1.1 302 Found\r\nLocation: {location}\r\n\r\n".encode())
    resolver.side_effect = [dns_answer(PUBLIC), dns_answer("10.0.0.1")]
    with pytest.raises(http.FetchError):
        http.fetch_page("http://example.com/")
    assert connect.call_count == 1


def test_same_host_redirect_revalidates_dns(network):
    resolver, connect, _ = network(b"HTTP/1.1 302 Found\r\nLocation: /new\r\n\r\n")
    resolver.side_effect = [dns_answer(PUBLIC), dns_answer("127.0.0.1")]
    with pytest.raises(http.FetchError):
        http.fetch_page("http://example.com/")
    assert resolver.call_count == 2
    assert connect.call_count == 1


def test_relative_public_redirect_and_gzip_still_work(network):
    body = gzip.compress("Zażółć gęślą".encode())
    resolver, connect, _ = network(
        b"HTTP/1.1 302 Found\r\nLocation: ../faq#menu\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n" + body,
    )
    page = http.fetch_page("http://example.com/path/start")
    assert page.url == "http://example.com/faq"
    assert page.text == "Zażółć gęślą"
    assert resolver.call_count == connect.call_count == 2


def test_redirect_chain_and_loop_are_bounded(network):
    _, connect, _ = network(
        *[f"HTTP/1.1 302 Found\r\nLocation: /{i}\r\n\r\n".encode() for i in range(5)]
    )
    with pytest.raises(http.FetchLimitExceeded):
        http.fetch_page("http://example.com/")
    assert connect.call_count == 4


@pytest.mark.parametrize(
    "headers,body",
    [
        (b"Content-Length: 101\r\n", b""),
        (b"", b"x" * 101),
        (b"Transfer-Encoding: chunked\r\n", b"65\r\n" + b"x" * 101 + b"\r\n0\r\n\r\n"),
        (b"Content-Encoding: gzip\r\n", gzip.compress(b"x" * 1000)),
    ],
)
def test_wire_and_decoded_limits(headers, body, network, monkeypatch):
    monkeypatch.setattr(http, "MAX_WIRE_BYTES", 100)
    monkeypatch.setattr(http, "MAX_BODY_BYTES", 100)
    _, _, wires = network(b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n" + body)
    with pytest.raises(http.FetchLimitExceeded):
        http.fetch_page("http://example.com/")
    assert wires[0].closed


@pytest.mark.parametrize(
    "response",
    [
        b"HTTP/1.1 403 Forbidden\r\n\r\nsecret",
        b"HTTP/1.1 302 Found\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: invalid\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nshort",
        b"HTTP/1.1 200 OK\r\nContent-Encoding: br\r\n\r\nxx",
        b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\nxx",
        b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n" + gzip.compress(b"x")[:-2],
        b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n" + gzip.compress(b"x") * 2,
    ],
)
def test_malformed_or_failed_response_is_closed(response, network):
    _, _, wires = network(response)
    with pytest.raises(http.FetchError):
        http.fetch_page("http://example.com/")
    assert wires[0].closed


def test_slow_body_is_interrupted_even_after_http_client_detaches_socket(monkeypatch):
    stopped = threading.Event()
    sock = Mock()
    sock.shutdown.side_effect = lambda how: stopped.set()
    response = Mock(status=200)
    response.getheader.side_effect = lambda name, default=None: default
    response.read.side_effect = lambda size: b"" if stopped.wait(2) else b"too late"
    connection = Mock(sock=sock)

    def detach():
        connection.sock = None
        return response

    connection.getresponse.side_effect = detach
    monkeypatch.setattr(http, "_open_connection", lambda *args: connection)
    monkeypatch.setattr(http, "FETCH_SECONDS", 0.1)
    start = time.monotonic()
    with pytest.raises(http.FetchLimitExceeded):
        http.fetch_page(f"http://{PUBLIC}/")
    assert time.monotonic() - start < 1
    assert stopped.is_set()
    response.close.assert_called_once()
    connection.close.assert_called_once()


def test_dns_timeout_and_saturation_are_bounded(monkeypatch):
    release = threading.Event()
    finished = threading.Event()

    def slow_lookup(*args):
        release.wait(2)
        finished.set()
        return dns_answer(PUBLIC)

    monkeypatch.setattr(http, "_DNS_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(http.socket, "getaddrinfo", slow_lookup)
    monkeypatch.setattr(http, "FETCH_SECONDS", 0.05)
    try:
        with pytest.raises(http.FetchLimitExceeded, match="domeny"):
            http.fetch_page("http://example.com/")
        with pytest.raises(http.FetchLimitExceeded, match="zajęty"):
            http.fetch_page("http://example.com/")
    finally:
        release.set()
        assert finished.wait(1)


@pytest.mark.parametrize(
    "limits",
    [
        {"max_requests": 1},
        {"max_bytes": 3},
    ],
)
def test_crawl_budget_is_shared_across_fetches_and_reset(limits, network):
    _, connect, _ = network(*[b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"] * 3)
    with http.crawl_fetch_budget(http.CrawlBudget(**limits)):
        assert http.fetch_page("http://example.com/").body == b"OK"
        with pytest.raises(http.FetchLimitExceeded):
            http.fetch_page("http://example.com/two")
    assert http.fetch_page("http://example.com/three").body == b"OK"


def test_crawl_deadline_prevents_network(network):
    resolver, connect, _ = network()
    with http.crawl_fetch_budget(http.CrawlBudget(deadline=time.monotonic() - 1)):
        with pytest.raises(http.FetchLimitExceeded):
            http.fetch_page("http://example.com/")
    resolver.assert_not_called()
    connect.assert_not_called()


def test_unicode_normalization_and_exact_host_scope():
    assert http.validate_url("https://ŻÓŁĆ.pl/żółć#sekcja") == (
        "https://xn--kda4b0koi.pl/%C5%BC%C3%B3%C5%82%C4%87"
    )
    assert http.same_site("https://example.com/faq", "http://EXAMPLE.com./old")
    assert not http.same_site("https://example.com.evil.org/", "https://example.com")
    assert not http.same_site("https://example.com@evil.org/", "https://example.com")
