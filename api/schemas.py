"""
Kształty żądań i odpowiedzi wyłącznie na potrzeby dokumentacji OpenAPI.

Część widoków to zwykłe APIView zwracające Response(dict). Bez tych opisów
generator nie ma czego pokazać i po cichu pomija endpoint — a pominięte były
akurat te publiczne, od których zaczyna każdy integrujący widget.

Te serializery nic nie walidują: opisują to, co widoki i tak zwracają.
"""
from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    """Krótkie potwierdzenie operacji."""
    message = serializers.CharField()


class StatusSerializer(serializers.Serializer):
    status = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


# --- Widget (publiczny, X-API-Key) ---

class WidgetBrandingSerializer(serializers.Serializer):
    widget_position = serializers.CharField()
    widget_color = serializers.CharField()
    widget_title = serializers.CharField()
    branding_mode = serializers.ChoiceField(choices=["smart", "white_label"])
    widget_footer_text = serializers.CharField(allow_blank=True)
    widget_logo = serializers.URLField(allow_null=True)
    widget_avatar = serializers.URLField(allow_null=True)
    privacy_policy_url = serializers.CharField(allow_blank=True)
    widget_welcome_message = serializers.CharField(allow_blank=True)
    widget_suggested_questions = serializers.ListField(child=serializers.CharField())


class PublicChatResponseSerializer(serializers.Serializer):
    response = serializers.CharField(help_text="Odpowiedź bota.")
    source = serializers.ChoiceField(
        choices=["document", "faq", "gpt"],
        help_text=(
            "Na czym oparta jest odpowiedź: 'document' — fragmenty wgranych "
            "materiałów, 'faq' — wpis FAQ, 'gpt' — brak pokrycia w materiałach firmy."
        ),
    )
    tokens = serializers.IntegerField()
    sources = serializers.ListField(
        child=serializers.CharField(),
        help_text="Nazwy dokumentów, które trafiły do kontekstu odpowiedzi.",
    )


class PublicContactRequestSerializer(serializers.Serializer):
    contact = serializers.CharField(help_text="E-mail lub telefon odwiedzającego.")
    name = serializers.CharField(required=False, allow_blank=True)
    message = serializers.CharField(required=False, allow_blank=True)
    conversation_session_id = serializers.UUIDField(required=False)


# --- Panel (JWT) ---

class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=["owner", "employee", "viewer"])
    tenant_name = serializers.CharField()
    tenant_api_key = serializers.UUIDField(
        help_text="Klucz do osadzenia widgetu na stronie firmy."
    )


class KnowledgeSerializer(serializers.Serializer):
    gpt_prompt = serializers.CharField(
        allow_blank=True, help_text="Opis działalności firmy — główne źródło wiedzy bota."
    )
    regulamin = serializers.CharField(allow_blank=True)


class PrivacySettingsSerializer(serializers.Serializer):
    data_retention_days = serializers.IntegerField(
        min_value=0, help_text="Po ilu dniach usuwać rozmowy. 0 wyłącza usuwanie."
    )
    privacy_policy_url = serializers.CharField(allow_blank=True)


class ErasureResultSerializer(serializers.Serializer):
    deleted = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Liczba usuniętych rekordów w rozbiciu na modele.",
    )


class KnowledgeSummarySerializer(serializers.Serializer):
    has_description = serializers.BooleanField()
    documents = serializers.IntegerField()
    indexed_chunks = serializers.IntegerField()
    faqs = serializers.IntegerField()
    websites = serializers.IntegerField()
    is_empty = serializers.BooleanField(
        help_text="Brak jakiejkolwiek wiedzy — bot odmawia odpowiedzi na pytania o firmę."
    )


class ConversationCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    last_7d = serializers.IntegerField()
    last_30d = serializers.IntegerField()


class QuestionCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    last_7d = serializers.IntegerField()


class AnswerSourcesSerializer(serializers.Serializer):
    document = serializers.IntegerField()
    faq = serializers.IntegerField()
    gpt = serializers.IntegerField()


class UsageSerializer(serializers.Serializer):
    used = serializers.IntegerField()
    limit = serializers.IntegerField(allow_null=True)
    plan = serializers.CharField(allow_null=True)


class UnansweredSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    question = serializers.CharField()
    asked_at = serializers.DateTimeField()


class AnalyticsSerializer(serializers.Serializer):
    knowledge = KnowledgeSummarySerializer()
    conversations = ConversationCountsSerializer()
    questions = QuestionCountsSerializer()
    answer_sources = AnswerSourcesSerializer()
    usage = UsageSerializer()
    unanswered = UnansweredSerializer(many=True)


class InvitationPreviewSerializer(serializers.Serializer):
    company = serializers.CharField()
    email = serializers.EmailField()
    role = serializers.CharField()
    is_valid = serializers.BooleanField()
    expires_at = serializers.DateTimeField(allow_null=True)


class AcceptInvitationRequestSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="PDF, DOCX, TXT lub MD.")
    name = serializers.CharField(required=False)


class CheckoutRequestSerializer(serializers.Serializer):
    plan_type = serializers.ChoiceField(choices=["pro", "enterprise"])


class CheckoutResponseSerializer(serializers.Serializer):
    checkout_url = serializers.URLField()


class CurrentSubscriptionSerializer(serializers.Serializer):
    plan = serializers.CharField(allow_null=True)
    name = serializers.CharField(allow_null=True)
    in_catalogue = serializers.BooleanField(
        help_text="Czy bieżący plan pochodzi z aktualnego cennika."
    )
    is_active = serializers.BooleanField()
    used = serializers.IntegerField()
    limit = serializers.IntegerField()
    renews_at = serializers.DateField(allow_null=True)


class PlanSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    price_pln = serializers.IntegerField()
    message_limit = serializers.IntegerField()
    white_label = serializers.BooleanField()
    available = serializers.BooleanField(
        help_text="Czy plan ma skonfigurowaną cenę w Stripe i da się go kupić."
    )
    current = serializers.BooleanField()


class BillingOverviewSerializer(serializers.Serializer):
    current = CurrentSubscriptionSerializer()
    plans = PlanSerializer(many=True)
