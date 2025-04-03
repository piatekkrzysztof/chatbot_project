from django.urls import path
from .views.chat import ChatWithGPTView
from .views.widget import WidgetSettingsView

urlpatterns = [
    path("chat/", ChatWithGPTView.as_view(), name="chat"),
    path("widget-settings/", WidgetSettingsView.as_view(), name="widget-settings"),
]
