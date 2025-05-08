from django.db import models
from accounts.models import Tenant
from pgvector.django import VectorField


class Document(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=255, default="Untitled")
    content = models.TextField(blank=True)
    file = models.FileField(upload_to="documents/", null=True, blank=True)
    processed = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"


class DocumentChunk(models.Model):
    document = models.ForeignKey("Document", on_delete=models.CASCADE, related_name="chunks")
    content = models.TextField()
    embedding = VectorField(dimensions=1536)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Chunk of {self.document.name}"


class WebsiteSource(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="website_sources"
    )
    name = models.CharField(max_length=255, default="Strona WWW klienta")
    url = models.URLField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tenant", "url")

    def __str__(self):
        return f"{self.name} ({self.url})"
