from rest_framework import routers
from .views.documents import DocumentViewSet
from .views.users import UserViewSet  # nowy widok User

router = routers.DefaultRouter()

router.register(r'documents', DocumentViewSet, basename='documents')
router.register(r'users', UserViewSet, basename='users')