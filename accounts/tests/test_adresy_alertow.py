import pytest
from django.core.exceptions import ImproperlyConfigured

from accounts.czuwanie import BrakAdresuAlertow, adresy_operatora


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("one@example.com", ["one@example.com"]),
        (" one@example.com, two@example.com ", ["one@example.com", "two@example.com"]),
        ("one@example.com,one@example.com", ["one@example.com"]),
    ],
)
def test_explicit_list_overrides_sender(settings, configured, expected):
    settings.EMAIL_ALERTOW = configured
    settings.DEFAULT_FROM_EMAIL = "sender@example.com"
    assert adresy_operatora() == expected


@pytest.mark.parametrize("configured", ["", "   ", None])
def test_missing_list_never_uses_sender_as_recipient(settings, configured):
    settings.EMAIL_ALERTOW = configured
    settings.DEFAULT_FROM_EMAIL = "SM-art <sender@example.com>"
    with pytest.raises(BrakAdresuAlertow):
        adresy_operatora()


def test_missing_both_destinations_fails(settings):
    settings.EMAIL_ALERTOW = ""
    settings.DEFAULT_FROM_EMAIL = ""
    with pytest.raises(BrakAdresuAlertow):
        adresy_operatora()


@pytest.mark.parametrize(
    "configured",
    [
        "one@example.com,not-an-email",
        "one@example.com,",
        ",one@example.com",
        "one@example.com,,two@example.com",
        "one@example.com;two@example.com",
        "one@example.com\r\nBcc: attacker@example.com",
        "one@example.com,\ntwo@example.com",
    ],
)
def test_invalid_list_does_not_silently_use_sender_or_skip_address(settings, configured):
    settings.EMAIL_ALERTOW = configured
    settings.DEFAULT_FROM_EMAIL = "sender@example.com"
    with pytest.raises(ImproperlyConfigured) as error:
        adresy_operatora()
    assert configured not in str(error.value)
    assert "one@example.com" not in str(error.value)
