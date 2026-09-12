"""Server-side lifetime and revocation shared by a login's token descendants."""

import uuid

from django.conf import settings
from django.db import models


class LoginSession(models.Model):
    id: models.UUIDField = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user: models.ForeignKey = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    password_fingerprint: models.CharField = models.CharField(max_length=64)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    expires_at: models.DateTimeField = models.DateTimeField(db_index=True)
    revoked_at: models.DateTimeField = models.DateTimeField(null=True)
