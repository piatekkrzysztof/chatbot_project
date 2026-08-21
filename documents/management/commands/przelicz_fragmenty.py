"""
Przelicza fragmenty i wektory istniejących dokumentów.

Zmiana sposobu dzielenia nie rusza tego, co już leży w bazie: bot dalej
odpowiada z fragmentów pociętych po staremu, czyli z pomieszanymi tematami
i nagłówkami odciętymi od treści. Ta komenda przelicza je od nowa.

Kosztuje realne wywołania API modelu embeddingów, więc domyślnie tylko
pokazuje, co by zrobiła. Do zapisu trzeba dopisać --wykonaj.
"""
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Tenant
from documents.models import Document, DocumentChunk
from documents.utils.embedding_generator import generate_embeddings_for_document
from documents.utils.fragmenty import podziel_na_fragmenty


class Command(BaseCommand):
    help = "Przelicza fragmenty dokumentów nowym podziałem (domyślnie na sucho)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--firma", type=int, metavar="ID",
            help="Tylko ta firma. Bez tego: wszystkie.",
        )
        parser.add_argument(
            "--wykonaj", action="store_true",
            help="Zapisz zmiany. Bez tego komenda tylko pokazuje, co by zrobiła.",
        )

    def handle(self, *args, **opcje):
        dokumenty = Document.objects.select_related("tenant").exclude(content="").order_by("id")

        if opcje.get("firma"):
            if not Tenant.objects.filter(pk=opcje["firma"]).exists():
                raise CommandError(f"Nie ma firmy o id {opcje['firma']}.")
            dokumenty = dokumenty.filter(tenant_id=opcje["firma"])

        if not dokumenty.exists():
            self.stdout.write("Brak dokumentów z treścią — nie ma czego przeliczać.")
            return

        na_sucho = not opcje["wykonaj"]
        if na_sucho:
            self.stdout.write(self.style.WARNING(
                "PRÓBA NA SUCHO — nic nie zostanie zapisane. Dopisz --wykonaj, żeby przeliczyć.\n"
            ))

        bylo_lacznie = nowych_lacznie = 0

        for dokument in dokumenty:
            bylo = DocumentChunk.objects.filter(document=dokument).count()
            # Na sucho liczymy sam podział — bez wywołań API, więc bez kosztu
            nowych = (
                len(podziel_na_fragmenty(dokument.content))
                if na_sucho
                else generate_embeddings_for_document(dokument)
            )
            bylo_lacznie += bylo
            nowych_lacznie += nowych

            self.stdout.write(
                f"#{dokument.id:<5} {dokument.tenant.name[:22]:<24} "
                f"{dokument.name[:38]:<40} {bylo:>4} -> {nowych:>4}"
            )

        self.stdout.write("")
        self.stdout.write(f"Dokumentów: {dokumenty.count()}   fragmentów: {bylo_lacznie} -> {nowych_lacznie}")
        if na_sucho:
            self.stdout.write(self.style.WARNING("Nic nie zapisano. Dopisz --wykonaj."))
        else:
            self.stdout.write(self.style.SUCCESS("Przeliczone."))
