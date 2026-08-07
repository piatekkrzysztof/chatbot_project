from rest_framework import routers
from .views.documents import DocumentsViewSet, WebsiteSourceViewSet
from .views.faq import FAQViewSet
from .views.users import UserViewSet  # nowy widok User

router = routers.DefaultRouter()

router.register(r'documents', DocumentsViewSet, basename='documents')
router.register(r'users', UserViewSet, basename='users')
router.register(r'website-sources', WebsiteSourceViewSet, basename='website-sources')
router.register(r'faq', FAQViewSet, basename='faq')