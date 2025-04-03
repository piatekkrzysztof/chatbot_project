from django.urls import path
from api.views.chat import ChatWithGPTView
from api.views.widget import WidgetSettingsAPIView

urlpatterns = [
    path("chat/", ChatWithGPTView.as_view(), name="chat"),
    path("widget-settings/", WidgetSettingsAPIView.as_view(), name="widget-settings"),
    ]