from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):
    # Musi wykonać się PRZED 0004, które tworzy kolumnę typu vector.
    # Wcześniej zależność wskazywała 0004 i baza nie dawała się zbudować od zera.
    dependencies = [
        ("documents", "0003_document_file_document_processed_and_more"),
    ]

    operations = [
        VectorExtension(),
    ]
