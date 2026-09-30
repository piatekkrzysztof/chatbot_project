"""Trwały wynik okresowej kontroli płatności; nie nadaje uprawnień."""

from django.db import models


class KontrolaStripe(models.Model):
    tenant = models.OneToOneField(
        "accounts.Tenant", on_delete=models.CASCADE, related_name="kontrola_stripe"
    )
    probowano_at = models.DateTimeField(null=True, blank=True, db_index=True)
    uzgodniono_at = models.DateTimeField(null=True, blank=True)
    blad = models.CharField(max_length=64, blank=True)
    alarm_at = models.DateTimeField(null=True, blank=True)
