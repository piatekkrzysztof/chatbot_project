"""Syntetyczne firmy do pomiaru. Wypisuje JSON z kluczami widgetu i tokenami panelu."""

import json
import random
import uuid
from datetime import date, timedelta

from accounts.models import CustomUser, Subscription, Tenant, UserRole
from api.session_tokens import SessionRefreshToken
from documents.models import Document, DocumentChunk
from documents.wymiar import WYMIAR_WEKTORA

FIRMY = 4
FRAGMENTY = 500

wynik = []
for numer in range(FIRMY):
    nazwa = f"pomiar-{numer}"
    tenant = Tenant.objects.filter(name=nazwa).first()
    if tenant is None:
        tenant = Tenant.objects.create(name=nazwa, owner_email=f"{nazwa}@example.invalid")
        Subscription.objects.create(
            tenant=tenant,
            plan_type="pro",
            is_active=True,
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=30),
        )
        dokument = Document.objects.create(
            tenant=tenant, name="cennik", content="x", processed=True
        )
        DocumentChunk.objects.bulk_create(
            DocumentChunk(
                document=dokument,
                content=f"Fragment {i}: " + "oferta tortów i dekoracji okolicznościowych " * 12,
                embedding=[random.uniform(-1, 1) for _ in range(WYMIAR_WEKTORA)],
            )
            for i in range(FRAGMENTY)
        )
        CustomUser.objects.create_user(
            username=f"{nazwa}-{uuid.uuid4().hex[:6]}",
            email=f"{nazwa}@example.invalid",
            password=uuid.uuid4().hex,
            tenant=tenant,
            role=UserRole.EMPLOYEE,
        )
    uzytkownik = CustomUser.objects.filter(tenant=tenant).first()
    token = SessionRefreshToken.for_user(uzytkownik)
    wynik.append({"api_key": str(tenant.api_key), "token": str(token.access_token)})

print("DANE=" + json.dumps(wynik))
