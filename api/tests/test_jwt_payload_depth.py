"""Reject excessive JWT payload nesting at the SimpleJWT error boundary."""

import jwt
import pytest
from rest_framework_simplejwt.backends import TokenBackend
from rest_framework_simplejwt.exceptions import TokenBackendError


@pytest.mark.parametrize("verify", [True, False])
def test_nested_payload_is_token_error_instead_of_uncaught_recursion(verify):
    key = "synthetic-jwt-regression-key-never-used-in-production"
    payload = b'{"nested":' + b"[" * 20000 + b"0" + b"]" * 20000 + b"}"
    token = jwt.api_jws.encode(payload, key, algorithm="HS256")
    backend = TokenBackend(algorithm="HS256", signing_key=key)

    with pytest.raises(TokenBackendError):
        backend.decode(token, verify=verify)
