from django.urls import path
from .views.chat import ChatAPIView
from .views.widget import WidgetSettingsAPIView

urlpatterns = [
    path("chat/", ChatAPIView.as_view(), name="chat"),
    path("widget-settings/", WidgetSettingsAPIView.as_view(), name="widget-settings"),
]
]