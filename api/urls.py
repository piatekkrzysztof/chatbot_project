from django.urls import path, include
from .views.chat import ChatWithGPTView
from .views.chat_csv import ExportPromptLogsCSVView, ImportPromptLogsCSVView
from .views.widget import (
    WidgetSettingsAPIView, PublicFAQView, PublicChatView,
    PublicChatStreamView, TenantWidgetSettingsView,
)
from .views.feedback import PublicFeedbackView, SubmitFeedbackView
from .views.accounts import ClientRegisterView, LoginView, MeView, CreateInvitationView, AcceptInvitationView, \
    InvitationListView, InvitationPreviewView, InvitationRevokeView
from .views.stripe import BillingOverviewView, CreateCheckoutSessionView
from .views.stripe_webhook import stripe_webhook
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.utils import extend_schema

# TokenRefreshView pochodzi z biblioteki, więc opisujemy go tutaj zamiast
# dekorować cudzą klasę w jej module
TokenRefreshView = extend_schema(
    tags=["Konto"], summary="Odśwież token dostępu"
)(TokenRefreshView)
from .routers import router
from api.views.documents import UploadDocumentView, DocumentDetailView, DocumentChunkListView
from api.views.diagnostyka import DiagnostykaAdresuView
from api.views.diagnostyka_zadan import DiagnostykaZadanView
from api.views.stripe import PublicPricingView
from .views.chat_logs import PromptLogListView
from .views.analytics import TenantAnalyticsView
from .views.contact import PublicContactRequestView
from .views.knowledge import TenantKnowledgeView
from .views.privacy import ConversationEraseView, TenantPrivacySettingsView

urlpatterns = [
    path('', include(router.urls)),
    path('widget-settings/', WidgetSettingsAPIView.as_view(), name='widget-settings'),
    path('chat/', ChatWithGPTView.as_view(), name='chat'),
    path("chat/feedback/", SubmitFeedbackView.as_view(), name="chat-feedback"),
    path("chat/logs/", PromptLogListView.as_view(), name="chat-logs"),
    path("chat/export/", ExportPromptLogsCSVView.as_view(), name="chat-export-csv"),
    path("chat/import/", ImportPromptLogsCSVView.as_view(), name="chat-import-csv"),
    path('accounts/register/', ClientRegisterView.as_view(), name='register'),
    path('accounts/login/', LoginView.as_view(), name='login'),
    path('accounts/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('accounts/me/', MeView.as_view(), name='me'),
    path('accounts/invitations/', CreateInvitationView.as_view(), name='invite-user'),
    path("accounts/invitations/list/", InvitationListView.as_view(), name="list-invitations"),
    path('accounts/accept-invite/', AcceptInvitationView.as_view(), name='accept-invite'),
    path(
        'accounts/invitations/<uuid:token>/preview/',
        InvitationPreviewView.as_view(), name='invitation-preview',
    ),
    path(
        'accounts/invitations/<int:pk>/',
        InvitationRevokeView.as_view(), name='invitation-revoke',
    ),
    path("documents-upload/", UploadDocumentView.as_view(), name="upload-document"),
    path("documents/<int:pk>/", DocumentDetailView.as_view(), name="document-detail"),
    path("documents/<int:document_id>/chunks/", DocumentChunkListView.as_view(), name="document-chunks"),
    # path("widget/settings/", WidgetSettingsAPIView.as_view(), name="widget-settings"),
    path("widget/faq/", PublicFAQView.as_view(), name="widget-faq"),
    path("widget/chat/", PublicChatView.as_view(), name="widget-chat"),
    path("widget/chat/stream/", PublicChatStreamView.as_view(), name="widget-chat-stream"),
    path("widget/contact/", PublicContactRequestView.as_view(), name="widget-contact"),
    path("widget/feedback/", PublicFeedbackView.as_view(), name="widget-feedback"),
    path("widget-settings/mine/", TenantWidgetSettingsView.as_view(), name="widget-settings-mine"),
    path("diagnostyka/adres/", DiagnostykaAdresuView.as_view(), name="diagnostyka-adres"),
    path("diagnostyka/zadania/", DiagnostykaZadanView.as_view(), name="diagnostyka-zadania"),
    path("billing/cennik/", PublicPricingView.as_view(), name="public-pricing"),
    path("knowledge/", TenantKnowledgeView.as_view(), name="tenant-knowledge"),
    path("privacy/", TenantPrivacySettingsView.as_view(), name="tenant-privacy"),
    path(
        "privacy/conversations/<uuid:session_id>/",
        ConversationEraseView.as_view(),
        name="conversation-erase",
    ),
    path("analytics/", TenantAnalyticsView.as_view(), name="analytics"),
    path("billing/plans/", BillingOverviewView.as_view(), name="billing-plans"),
    path("billing/create-checkout-session/", CreateCheckoutSessionView.as_view()),
    # Trasy brakowało w ogóle — Stripe nie miał dokąd wysyłać zdarzeń,
    # więc kod webhooka nigdy się nie wykonał
    path("billing/webhook/", stripe_webhook, name="stripe-webhook"),

]
