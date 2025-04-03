from django.db import models
from accounts.models import Tenant


class Document(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    content = models.TextField(blank=True, null=True)  # Przetworzony tekst z dokumentu

    def __str__(self):
        return f'{self.title} ({self.tenant.name})'
