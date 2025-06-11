from rest_framework.exceptions import ValidationError
from documents.models import Document

PLAN_DOCUMENT_LIMITS = {
    "free": 50,
    "pro": 200,
    "enterprise": 1000,
}

DEFAULT_LIMIT = PLAN_DOCUMENT_LIMITS["free"]

def validate_document_limit(tenant):
    plan = getattr(getattr(tenant, "subscription", None), "plan_type", "free").lower()
    max_limit = PLAN_DOCUMENT_LIMITS.get(plan, DEFAULT_LIMIT)

    current_count = Document.objects.filter(tenant=tenant).count()
    if current_count >= max_limit:
        raise ValidationError(
            f"Limit dokumentów ({max_limit}) dla planu '{plan}' został przekroczony."
        )
