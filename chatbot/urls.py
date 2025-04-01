from django.urls import path
from . import views

urlpatterns=[
    path('chat/', views.chat_with_gpt, name="chat_with_gpt"),
    path('api/widget-settings/', views.widget_settings, name='widget-settings'),
]