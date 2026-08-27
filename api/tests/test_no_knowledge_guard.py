"""
Zabezpieczenie przed zmyślaniem, gdy bot nie ma żadnej wiedzy o firmie.

Na produkcji tenant bez opisu działalności, dokumentów i FAQ odpowiadał na
"Czym zajmuje się wasza firma?" wymyślonym profilem działalności wywnioskowanym
z samej nazwy — i podawał go jako fakt. Pytania o ceny czy godziny model odrzucał
poprawnie, więc luka dotyczyła wyłącznie pytań o tożsamość i zakres usług.
Na stronie klienta oznacza to bota wymyślającego klientowi ofertę.
"""

import pytest

from api.utils.chat_engine import (
    build_system_prompt,
    has_company_knowledge,
)
from chat.models import FAQ

NO_KNOWLEDGE_MARKER = "nie masz żadnych informacji o tej firmie"


@pytest.mark.django_db
def test_tenant_without_any_knowledge_gets_explicit_warning(tenant):
    tenant.gpt_prompt = ""
    tenant.regulamin = ""
    tenant.save()

    prompt = build_system_prompt(tenant, chunks=[], faqs=[])

    assert NO_KNOWLEDGE_MARKER in prompt


@pytest.mark.django_db
def test_company_description_removes_the_warning(tenant):
    tenant.gpt_prompt = "Sprzedajemy rowery elektryczne."
    tenant.regulamin = ""
    tenant.save()

    prompt = build_system_prompt(tenant, chunks=[], faqs=[])

    assert NO_KNOWLEDGE_MARKER not in prompt
    assert "Sprzedajemy rowery elektryczne." in prompt


@pytest.mark.django_db
def test_faq_alone_counts_as_knowledge(tenant):
    tenant.gpt_prompt = ""
    tenant.regulamin = ""
    tenant.save()
    faq = FAQ.objects.create(tenant=tenant, question="Jakie macie godziny?", answer="9-17.")

    prompt = build_system_prompt(tenant, chunks=[], faqs=[faq])

    assert NO_KNOWLEDGE_MARKER not in prompt


@pytest.mark.django_db
def test_regulamin_alone_counts_as_knowledge(tenant):
    tenant.gpt_prompt = ""
    tenant.regulamin = "Zwroty w ciągu 14 dni."
    tenant.save()

    assert has_company_knowledge(tenant, chunks=[], faqs=[]) is True


@pytest.mark.django_db
def test_prompt_forbids_guessing_from_company_name(tenant):
    """Klasa pytań, na której model przeciekał, ma być wymieniona wprost."""
    prompt = build_system_prompt(tenant, chunks=[], faqs=[])

    assert "Nigdy nie zgaduj na podstawie nazwy firmy" in prompt
    assert "czym firma się zajmuje" in prompt
