from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    QuestionViewSet,
    QuestionTagViewSet,
    QuestionReviewViewSet,
)

router = DefaultRouter()
router.register(r'questions', QuestionViewSet, basename='question')
router.register(r'question-tags', QuestionTagViewSet, basename='question-tag')
router.register(r'question-reviews', QuestionReviewViewSet, basename='question-review')

urlpatterns = [
    path('', include(router.urls)),
]
