"""Trwały, pojedynczy slot zakupu firmy; nie jest potwierdzeniem zapłaty."""

import uuid

from django.db import models
from django.utils import timezone


class ProbaZakupu(models.Model):
    tenant = models.OneToOneField(
        "accounts.Tenant", on_delete=models.CASCADE, related_name="proba_zakupu"
    )
    klucz = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    parametry = models.JSONField(default=dict, blank=True)
    sesja_id = models.CharField(max_length=255, blank=True)
    rozpoczeta_at = models.DateTimeField(default=timezone.now)
    # Migracja oznacza istniejące firmy do sprawdzenia dawnych Checkoutów.
    # Nowe firmy nie mogły utworzyć sesji starym kodem po zakończonym wdrożeniu.
    sprawdzone_stare_sesje = models.BooleanField(default=True)
