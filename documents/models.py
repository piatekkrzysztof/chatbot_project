from django.db import models

from accounts.models import Tenant


class Document(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    content = models.TextField()

    def __str__(self):
        return f"{self.tenant.name} - {self.title}"
