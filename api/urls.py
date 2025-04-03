from django.urls import path
from api.views.chat import ChatWithGPTView
from api.views.widget import WidgetSettingsAPIView
from api.views.documents import DocumentUploadView

urlpatterns = [
    path("chat/", ChatWithGPTView.as_view(), name="chat"),
    path("widget-settings/", WidgetSettingsAPIView.as_view(), name="widget-settings"),
    path("documents/upload/", DocumentUploadView.as_view(), name="document-upload"),
    ]