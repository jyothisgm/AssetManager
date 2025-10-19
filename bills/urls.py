from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BillViewSet, BillItemViewSet

router = DefaultRouter()
router.register(r'bills', BillViewSet, basename='bill')
router.register(r'items', BillItemViewSet, basename='billitem')

urlpatterns = [
    path('', include(router.urls)),
]
