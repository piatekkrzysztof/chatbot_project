import pytest
from django.contrib.admin.sites import AdminSite
from chat.models import PromptLog, Tenant, Conversation
from chat.admin import PromptLogAdmin
from django.utils.timezone import now
from django.http import HttpRequest


@pytest.mark.django_db
def test_promptlog_export_as_csv():
    tenant = Tenant.objects.create(name="Tenant A", api_key="aaa")
    conv = Conversation.objects.create(id="c1", tenant=tenant)

    PromptLog.objects.create(
        tenant=tenant,
        conversation=conv,
        model="gpt-3.5-turbo",
        prompt="Jak działa system?",
        response="System działa tak, że...",
        tokens=150,
        source="gpt"
    )

    ma = PromptLogAdmin(PromptLog, AdminSite())
    queryset = PromptLog.objects.all()
    request = HttpRequest()
    response = ma.export_as_csv(request, queryset)

    content = response.getvalue().decode("utf-8")
    assert "prompt,response" in content or "prompt" in content  # zależnie od wersji
    assert "Jak działa system?" in content
    assert "System działa tak" in content
    assert "gpt-3.5-turbo" in content
