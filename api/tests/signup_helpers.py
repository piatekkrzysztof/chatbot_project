import re

from django.core import mail
from rest_framework.test import APIClient


def latest_token():
    return re.search(r"#token=([A-Za-z0-9_-]{43})", mail.outbox[-1].body).group(1)


def complete_registration(response, password):
    """Continue the real two-step API flow in existing billing/auth regressions."""
    if response.status_code != 202:
        return response
    return APIClient().post(
        "/api/accounts/registration/activate/",
        {"token": latest_token(), "password": password},
        format="json",
    )
