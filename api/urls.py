from django.urls import path, include
from .views.chat import ChatWithGPTView
from .views.widget import WidgetSettingsAPIView
from .views.feedback import SubmitFeedbackView
from .views.accounts import RegisterView, LoginView, MeView, CreateInvitationView, AcceptInvitationView, \
    InvitationListView
from rest_framework_simplejwt.views import TokenRefreshView
from .routers import router
from api.views.documents import UploadDocumentView, DocumentDetailView, DocumentChunkListView
from .views.chat_logs import PromptLogListView

urlpatterns = [
    path('', include(router.urls)),
    path('widget-settings/', WidgetSettingsAPIView.as_view(), name='widget-settings'),
    path('chat/', ChatWithGPTView.as_view(), name='chat'),
    path("chat/feedback/", SubmitFeedbackView.as_view(), name="chat-feedback"),
    path("chat/logs/", PromptLogListView.as_view(), name="chat-logs"),
    path('accounts/register/', RegisterView.as_view(), name='register'),
    path('accounts/login/', LoginView.as_view(), name='login'),
    path('accounts/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('accounts/me/', MeView.as_view(), name='me'),
    path('accounts/invitations/', CreateInvitationView.as_view(), name='invite-user'),
    path("accounts/invitations/list/", InvitationListView.as_view(), name="list-invitations"),
    path('accounts/accept-invite/', AcceptInvitationView.as_view(), name='accept-invite'),
    path("documents-upload/", UploadDocumentView.as_view(), name="upload-document"),
    path("documents/<int:pk>/", DocumentDetailView.as_view(), name="document-detail"),
    path("documents/<int:document_id>/chunks/", DocumentChunkListView.as_view(), name="document-chunks"),
    path("widget/settings/", WidgetSettingsAPIView.as_view(), name="widget-settings"),

]
