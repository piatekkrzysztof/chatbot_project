"""
Zakłada firmę wraz z kontem właściciela.

Standardowe `createsuperuser` tu nie wystarcza: CustomUser ma wymagane pole
`tenant`, o które ta komenda nie pyta, więc kończy się naruszeniem NOT NULL.
Ta komenda tworzy jedno i drugie w komplecie — to też ścieżka onboardingu
każdego nowego klienta agencji.
"""
from datetime import date, timedelta
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Tenant, CustomUser, Subscription, UserRole


class Command(BaseCommand):
    help = "Tworzy firmę (tenant) wraz z kontem właściciela i subskrypcją."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Nazwa firmy")
        parser.add_argument("--email", required=True, help="E-mail właściciela (będzie też loginem)")
        parser.add_argument("--password", help="Hasło; pominięte = zapyta interaktywnie")
        parser.add_argument("--plan", default="pro", help="Nazwa planu (domyślnie: pro)")
        parser.add_argument("--message-limit", type=int, default=1000, help="Limit wiadomości/miesiąc")
        parser.add_argument(
            "--admin", action="store_true",
            help="Nadaj dostęp do panelu Django (/admin/)",
        )

    def handle(self, *args, **options):
        company = options["company"]
        email = options["email"]

        if CustomUser.objects.filter(username=email).exists():
            raise CommandError(f"Użytkownik {email} już istnieje.")

        password = options.get("password") or getpass("Hasło: ")
        if not password:
            raise CommandError("Hasło nie może być puste.")

        with transaction.atomic():
            tenant, created = Tenant.objects.get_or_create(
                name=company,
                defaults={"owner_email": email},
            )
            if not created:
                self.stdout.write(f"Firma '{company}' już istniała — dopinam do niej użytkownika.")

            user = CustomUser.objects.create_user(
                username=email,
                email=email,
                password=password,
                tenant=tenant,
                role=UserRole.OWNER,
            )
            if options["admin"]:
                user.is_staff = True
                user.is_superuser = True
                user.save(update_fields=["is_staff", "is_superuser"])

            Subscription.objects.get_or_create(
                tenant=tenant,
                defaults={
                    "plan_type": options["plan"],
                    "start_date": date.today(),
                    "end_date": date.today() + timedelta(days=365),
                    "message_limit": options["message_limit"],
                },
            )

        self.stdout.write(self.style.SUCCESS("\nGotowe."))
        self.stdout.write(f"  Firma        : {tenant.name}")
        self.stdout.write(f"  Login        : {user.username}")
        self.stdout.write(f"  Rola         : owner{' + admin Django' if options['admin'] else ''}")
        self.stdout.write(f"  Klucz widgetu: {tenant.api_key}")
        # Adres panelu bierzemy z konfiguracji, zamiast kazać go podmieniać
        # ręcznie. Ten fragment idzie prosto do wklejenia na stronę klienta,
        # a podstawienie "TWOJA-DOMENA" było krokiem, o którym łatwo zapomnieć —
        # skutkiem jest widget, który się nie ładuje, i szukanie przyczyny
        # gdzie indziej.
        from django.conf import settings

        adres_panelu = (settings.FRONTEND_URL or "").rstrip("/")
        if not adres_panelu:
            adres_panelu = "https://USTAW-FRONTEND_URL"
            self.stdout.write(self.style.WARNING(
                "\n  UWAGA: FRONTEND_URL nie jest ustawiony — w kodzie osadzenia "
                "poniżej trzeba podmienić adres ręcznie."
            ))

        self.stdout.write(
            f'\n  Kod osadzenia:\n  <script src="{adres_panelu}/embed.js" '
            f'data-key="{tenant.api_key}" async></script>\n'
        )
