"""One bounded child parser per application instance, with a clean environment."""

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from documents.file_limits import (
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    InvalidUpload,
    UploadTooLarge,
    bounded_read,
    extension,
    inspect_document,
)

PARSER_MEMORY_BYTES = 192 * 1024 * 1024
PARSER_SECONDS = 20
IMAGE_PARSER_SECONDS = 5
MAX_RESULT_BYTES = 16 * 1024 * 1024
PARSER_SCRIPT = Path(__file__).with_name("parser_worker.py")
_THREAD_LOCK = threading.Lock()


class ParserUnavailable(InvalidUpload):
    pass


def memory_budget():
    budget = PARSER_MEMORY_BYTES
    # Leave room for the existing service, rather than assuming the container has
    # 192 MiB free. This also makes low-memory hosts fail before starting a child.
    for maximum, usage in [
        ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
        (
            "/sys/fs/cgroup/memory/memory.limit_in_bytes",
            "/sys/fs/cgroup/memory/memory.usage_in_bytes",
        ),
    ]:
        try:
            headroom = int(Path(maximum).read_text()) - int(Path(usage).read_text())
        except (OSError, ValueError):
            continue
        budget = min(budget, headroom // 2)
        break
    if budget < 96 * 1024 * 1024:
        raise ParserUnavailable(
            "Serwer nie ma teraz zasobów na przetworzenie pliku. Spróbuj później."
        )
    return budget


@contextmanager
def parser_slot():
    if not _THREAD_LOCK.acquire(blocking=False):
        raise ParserUnavailable("Trwa przetwarzanie innego pliku. Spróbuj ponownie za chwilę.")
    handle = None
    try:
        identity = hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:16]
        path = Path(tempfile.gettempdir()) / f"chatbot-parser-{identity}.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        try:
            handle = os.fdopen(os.open(path, flags, 0o600), "r+b", buffering=0)
            if os.name == "nt":
                import msvcrt

                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"0")
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ParserUnavailable("Trwa przetwarzanie innego pliku. Spróbuj za chwilę.") from None
        yield
    finally:
        if handle is not None:
            handle.close()  # Closing releases the OS lock, including after parser failure.
        _THREAD_LOCK.release()


def _dependency_paths():
    # Support both a normal installation and isolated --target test dependencies.
    return sorted(
        {
            str(Path(importlib.util.find_spec(name).origin).parent.parent)
            for name in ("pypdf", "PIL", "defusedxml")
        }
    )


def parse_bytes(data, name, *, image=False):
    if len(data) > (MAX_IMAGE_BYTES if image else MAX_DOCUMENT_BYTES):
        raise UploadTooLarge("Plik przekracza dozwolony rozmiar.")
    suffix = extension(name)
    if not image:
        inspect_document(data, name, full=False)
    with parser_slot():
        command = [
            sys.executable,
            "-I",
            str(PARSER_SCRIPT),
            "image" if image else "document",
            suffix,
            str(memory_budget()),
            json.dumps(_dependency_paths()),
        ]
        environment = {
            key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ
        }
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(
                    command,
                    input=data,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=IMAGE_PARSER_SECONDS if image else PARSER_SECONDS,
                    env=environment,
                    check=False,
                    **options,
                )
            except subprocess.TimeoutExpired:
                raise InvalidUpload(
                    "Przetwarzanie pliku trwało zbyt długo. Użyj prostszego pliku."
                ) from None
            except OSError:
                raise ParserUnavailable("Nie udało się uruchomić przetwarzania pliku.") from None
            output.seek(0)
            raw = output.read(MAX_RESULT_BYTES + 1)
        if len(raw) > MAX_RESULT_BYTES:
            raise UploadTooLarge("Wynik przetwarzania przekracza limit rozmiaru.")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise InvalidUpload("Plik jest zbyt złożony albo nie udało się go odczytać.") from None
        if value.get("error") == "unavailable":
            raise ParserUnavailable("Nie udało się zabezpieczyć procesu przetwarzania pliku.")
        if value.get("error") == "limit":
            raise UploadTooLarge(value.get("message", "Plik przekracza limit przetwarzania."))
        if result.returncode != 0 or value.get("error"):
            kind = "PDF" if suffix == ".pdf" else "obrazu" if image else "dokumentu"
            raise InvalidUpload(value.get("message", f"Nie udało się odczytać {kind}."))
        if image:
            return base64.b64decode(value["image"], validate=True)
        return value["text"]


def parse_document(handle, name, limit=MAX_DOCUMENT_BYTES):
    data = bounded_read(handle, min(limit, MAX_DOCUMENT_BYTES))
    return parse_bytes(data, name)
