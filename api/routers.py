from rest_framework import routers

from api.views.widget import WidgetDomainViewSet

from .views.contact import ContactRequestViewSet
from .views.documents import DocumentsViewSet, WebsiteSourceViewSet
from .views.faq import FAQViewSet
from .views.users import UserViewSet  # nowy widok User

# SimpleRouter, nie DefaultRouter: tamten dodawał GET /api/ z listą końcówek
# panelu, dostępną z samym jawnym kluczem widgetu. Nikt z niej nie korzystał.
router = routers.SimpleRouter()

router.register(r"documents", DocumentsViewSet, basename="documents")
router.register(r"users", UserViewSet, basename="users")
router.register(r"website-sources", WebsiteSourceViewSet, basename="website-sources")
router.register(r"faq", FAQViewSet, basename="faq")
router.register(r"contact-requests", ContactRequestViewSet, basename="contact-requests")
router.register(r"widget-domains", WidgetDomainViewSet, basename="widget-domain")
