from django.urls import path
from .views import chat_with_gpt, widget_settings

urlpatterns=[
    path('chat/', chat_with_gpt, name="chat_with_gpt"),
    path('api/widget-settings/', widget_settings, name='widget-settings'),
]