from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SourceDocumentViewSet, QuestionGenerationJobViewSet

router = DefaultRouter()
router.register(r'source-materials', SourceDocumentViewSet, basename='source-material')
router.register(r'question-generation-jobs', QuestionGenerationJobViewSet, basename='question-generation-job')

urlpatterns = [
    path('', include(router.urls)),
]
