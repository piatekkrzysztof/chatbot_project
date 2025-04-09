from django.urls import path, include
from .views.chat import ChatWithGPTView
from .views.widget import WidgetSettingsAPIView
from .views.accounts import RegisterView, LoginView, MeView, CreateInvitationView
from rest_framework_simplejwt.views import TokenRefreshView
from .routers import router

urlpatterns = [
    path('', include(router.urls)),
    path('widget-settings/', WidgetSettingsAPIView.as_view(), name='widget-settings'),
    path('chat/', ChatWithGPTView.as_view(), name='chat'),
    path('accounts/register/', RegisterView.as_view(), name='register'),
    path('accounts/login/', LoginView.as_view(), name='login'),
    path('accounts/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('accounts/me/', MeView.as_view(), name='me'),
    path('accounts/invitations/', CreateInvitationView.as_view(), name='invite-user'),

]
