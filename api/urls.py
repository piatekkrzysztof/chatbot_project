from django.urls import path, include
from .views.chat import ChatWithGPTView
from .views.widget import WidgetSettingsAPIView
from .routers import router  # NOWE

urlpatterns = [
    path('', include(router.urls)),  # NOWE
    path('widget-settings/', WidgetSettingsAPIView.as_view(), name='widget-settings'),
    path('chat/', ChatWithGPTView.as_view(), name='chat'),
]