from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PaperBlueprintViewSet,
    BlueprintSectionViewSet,
    BlueprintRuleViewSet,
    GeneratedPaperViewSet,
)

router = DefaultRouter()
router.register(r'paper-blueprints', PaperBlueprintViewSet, basename='paper-blueprint')
router.register(r'blueprint-sections', BlueprintSectionViewSet, basename='blueprint-section')
router.register(r'blueprint-rules', BlueprintRuleViewSet, basename='blueprint-rule')
router.register(r'generated-papers', GeneratedPaperViewSet, basename='generated-paper')

urlpatterns = [
    path('', include(router.urls)),
]
