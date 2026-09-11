"""Domain-separated encryption of MFA seeds; keys stay outside the database."""

import base64

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import models

PREFIX = "mfa:v1:"


def cipher():
    keys = [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]
    return MultiFernet(
        [
            Fernet(
                base64.urlsafe_b64encode(
                    HKDF(
                        algorithm=hashes.SHA256(),
                        length=32,
                        salt=b"sm-art-mfa-v1",
                        info=b"totp-seed-encryption",
                    ).derive(key.encode())
                )
            )
            for key in keys
        ]
    )


def encrypt(value):
    return PREFIX + cipher().encrypt(value.encode()).decode()


def decrypt(value):
    if not value.startswith(PREFIX):
        raise ValueError("Unencrypted MFA seed; migration required")
    return cipher().decrypt(value[len(PREFIX) :].encode()).decode()


class EncryptedMFAField(models.TextField):
    def to_python(self, value):
        if isinstance(value, str) and value.startswith(PREFIX):
            return decrypt(value)
        return value

    def from_db_value(self, value, expression, connection):
        return decrypt(value) if value is not None else value

    def get_prep_value(self, value):
        return encrypt(self.to_python(value)) if value is not None else value

    def value_to_string(self, obj):
        return encrypt(self.value_from_object(obj))

    def formfield(self, **kwargs):
        # Seeds never belong in ModelForms/admin pages.
        return None
