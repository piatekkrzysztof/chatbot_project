"""Origin checks for the endpoints that create, rotate or delete session cookies."""

from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.exceptions import PermissionDenied


def _origin(value, *, referer=False):
    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "*" in parsed.netloc
            or "\\" in value
            or (not referer and (parsed.path or parsed.query or parsed.fragment))
        ):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname, port
    except ValueError:
        return None


class SessionBoundaryMixin:
    """Fail closed without Origin/Referer, including when no cookie exists yet.

    SameSite does not distinguish a trusted panel from an untrusted sibling
    subdomain. CORS alone cannot stop a form POST or login CSRF. Native clients
    must also provide an explicitly trusted Origin for these browser endpoints.
    """

    def initial(self, request, *args, **kwargs):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if "Origin" in request.headers:
                source = _origin(request.headers["Origin"])
            else:
                source = _origin(request.headers.get("Referer"), referer=True)
            trusted = {
                _origin(value.rstrip("/"))
                for value in [settings.FRONTEND_URL, *settings.CSRF_TRUSTED_ORIGINS]
            }
            trusted.discard(None)
            if source is None or source not in trusted:
                raise PermissionDenied("Niedozwolone źródło żądania sesji.")
        return super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
