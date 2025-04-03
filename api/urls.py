from django.urls import path
from api.views.chat import ChatWithGPTView

urlpatterns = [
    path("chat/", ChatWithGPTView.as_view(), name="chat"),
]
