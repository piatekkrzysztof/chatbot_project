from django.db import models
from accounts.models import Tenant


class Document(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=255, default="Untitled")
    content = models.TextField(blank=True)
    file = models.FileField(upload_to="documents/", null=True, blank=True)
    processed = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

# class DocumentChunk(models.Model):
#     document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
#     content = models.TextField()
#     embedding = models.TextField()  # JSON string — lista wektorów (np. 1536 floats)
#
#     def __str__(self):
#         return f"Chunk {self.id} of {self.document.name}"
#
#     def get_embedding(self) -> list[float]:
#         return json.loads(self.embedding)
#
#     def set_embedding(self, vector: list[float]):
#         self.embedding = json.dumps(vector)
