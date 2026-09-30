import uuid

from django.db import models
from django.utils import timezone
from pgvector.django import VectorField

from accounts.models import Tenant
from documents.storage import DocumentStorage, private_document_name
from documents.wymiar import WYMIAR_WEKTORA


class Document(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=255, default="Untitled")
    content = models.TextField(blank=True)
    file = models.FileField(
        upload_to=private_document_name, storage=DocumentStorage(), null=True, blank=True
    )
    processed = models.BooleanField(default=False)
    processing_error: "models.CharField[str, str]" = models.CharField(
        max_length=300, blank=True, default=""
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=50, blank=True, null=True)

    # Adres, pod którym treść jest publicznie dostępna — wypełniany wyłącznie
    # dla stron zaimportowanych z witryny klienta. Bot podaje go odwiedzającemu
    # jako klikalne źródło odpowiedzi.
    #
    # Wgrane pliki zostają bez adresu celowo. Link do dokumentu firmy oznaczałby,
    # że każdy odwiedzający pobierze cennik wewnętrzny czy procedury, które
    # klient wgrał wyłącznie po to, żeby bot z nich korzystał.
    source_url = models.URLField(
        blank=True,
        default="",
        help_text="Publiczny adres źródła. Pusty dla wgranych plików.",
    )

    # Ile znaków widocznego tekstu miała strona w chwili pobrania. Razem
    # z długością `content` daje odpowiedź na pytanie „ile z tej strony
    # faktycznie wzięliśmy" — przez tygodnie strona główna klienta miała
    # w bazie 257 znaków z 10 037, a panel pokazywał zielone „gotowe", bo
    # formalnie dokument był przetworzony.
    #
    # Puste dla wgranych plików (nie ma czego porównywać) i dla podstron
    # pobranych przed wprowadzeniem tej miary.
    znakow_na_stronie = models.PositiveIntegerField(null=True, blank=True)

    # Czy dokument bierze udział w wyszukiwaniu. Powstało z obserwacji na
    # produkcji: sekcja "Kontakt / Porozmawiajmy o właściwym rozwiązaniu"
    # była najbliższym trafieniem dla sześciu z jedenastu pytań — o chrzciny,
    # kontenery z Chin, pogodę i pralki. Nie niesie żadnego faktu, więc leży
    # "średnio blisko" wszystkiego i zajmuje miejsce w piątce wyników także
    # przy pytaniach, na które klient ma prawdziwą odpowiedź.
    #
    # Odznaczenie NIE kasuje fragmentów, tylko je pomija przy wyszukiwaniu.
    # Dzięki temu włączenie z powrotem jest natychmiastowe i nie kosztuje
    # ponownego liczenia wektorów.
    #
    # To także jedyny sposób, żeby trwale wyłączyć podstronę pobraną ze strony
    # WWW: skasowany dokument wróci przy najbliższym odświeżeniu, wyłączony
    # zostaje wyłączony.
    uzywaj_w_wyszukiwaniu = models.BooleanField(
        default=True,
        verbose_name="Używaj w wyszukiwaniu",
    )

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

    def save(self, *args, **kwargs):
        from chatbot_project.pliki import zapis_z_plikami

        with zapis_z_plikami(
            self, update_fields=kwargs.get("update_fields"), using=kwargs.get("using")
        ):
            return super().save(*args, **kwargs)


class DocumentChunk(models.Model):
    document = models.ForeignKey("Document", on_delete=models.CASCADE, related_name="chunks")
    content = models.TextField()
    embedding = VectorField(dimensions=WYMIAR_WEKTORA)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Chunk of {self.document.name}"


class WebsiteSource(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="website_sources")
    name = models.CharField(max_length=255, default="Strona WWW klienta")
    url = models.URLField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Bez tej daty zadanie cykliczne pobierało wszystkie źródła przy każdym
    # przebiegu, niezależnie od planu — a cennik obiecuje różną częstotliwość.
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    # Kiedy ostatnio PRÓBOWALIŚMY, niezależnie od wyniku. Bez tego nieudane
    # pobranie jest nieodróżnialne od takiego, którego nigdy nie zlecono:
    # w obu przypadkach last_crawled_at zostaje puste.
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    # Treść ostatniego błędu. Klient musi wiedzieć, że import jego strony
    # się nie powiódł i dlaczego — inaczej ma bota bez wiedzy i bez wyjaśnienia.
    last_error = models.TextField(blank=True, default="")

    class Meta:
        unique_together = ("tenant", "url")

    def __str__(self):
        return f"{self.name} ({self.url})"


class UsunieciePliku(models.Model):
    # Bez FK do firmy/dokumentu: zlecenie musi przeżyć kaskadę usunięcia właściciela.
    firma_id = models.BigIntegerField(null=True, blank=True)
    magazyn = models.CharField(max_length=32)
    cel = models.CharField(max_length=64)
    nazwa = models.CharField(max_length=512)
    stan = models.CharField(max_length=16, default="oczekuje")
    proby = models.PositiveIntegerField(default=0)
    token = models.UUIDField(default=uuid.uuid4)
    utworzono_at = models.DateTimeField(auto_now_add=True)
    ponow_at = models.DateTimeField(default=timezone.now)
    dzierzawa_do = models.DateTimeField(null=True, blank=True)
    zakonczono_at = models.DateTimeField(null=True, blank=True)
    blad = models.CharField(max_length=64, blank=True)
    alarm_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["stan", "ponow_at"], name="plik_usun_due"),
            models.Index(fields=["stan", "dzierzawa_do"], name="plik_usun_lease"),
        ]
