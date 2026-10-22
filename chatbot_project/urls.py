"""
URL configuration for chatbot_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from chatbot_project.zdrowie import health_check

# Próbę Sentry robi `manage.py sprawdz_sentry`. Do 2.32.5 stał tu publiczny
# `/sentry-debug/` bez limitu: każde wejście dawało 500 i zdarzenie, więc kto
# chciał, wyczerpywał nim miesięczny limit zdarzeń i oślepiał monitoring.

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    # Dokumentacja celowo poza /api/ — TenantMiddleware wymaga tam tenanta,
    # a schemat ma być czytelny dla kogoś, kto dopiero szuka, jak się połączyć.
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("health/", health_check),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
