from django.db.models.signals import post_save
from django.dispatch import receiver
from documents.models import Document
from documents.tasks import extract_text_from_document, generate_embeddings_for_document


@receiver(post_save, sender=Document)
def handle_new_document(sender, instance, created, **kwargs):
    if created and instance.file and not instance.processed:
        extract_text_from_document.delay(instance.id)

    if instance.processed and not instance.chunks.exists():
        generate_embeddings_for_document.delay(instance.id)
