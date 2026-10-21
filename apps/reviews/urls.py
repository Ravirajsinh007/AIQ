from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    QuestionReviewWorkflowViewSet,
    QuestionReviewRecordViewSet,
)

router = DefaultRouter()
router.register(r'review-workflows', QuestionReviewWorkflowViewSet, basename='review-workflow')
router.register(r'review-audit-logs', QuestionReviewRecordViewSet, basename='review-audit-log')

urlpatterns = [
    path('', include(router.urls)),
]
