from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CodingSubmissionViewSet,
    ExamAttemptViewSet,
    ExamIntegrityFlagViewSet,
    ExamScheduleViewSet,
    ExamAnalyticsView,
    ExamGrievanceViewSet,
    HandwrittenAnswerSheetViewSet,
    RevaluationRequestViewSet,
)

router = DefaultRouter()
router.register('exams', ExamScheduleViewSet, basename='exam')
router.register('exam-attempts', ExamAttemptViewSet, basename='exam-attempt')
router.register('integrity-flags', ExamIntegrityFlagViewSet, basename='integrity-flag')
router.register('coding-submissions', CodingSubmissionViewSet, basename='coding-submission')
router.register('handwritten-answer-sheets', HandwrittenAnswerSheetViewSet, basename='handwritten-answer-sheet')
router.register('revaluation-requests', RevaluationRequestViewSet, basename='revaluation-request')
router.register('grievances', ExamGrievanceViewSet, basename='exam-grievance')

urlpatterns = [
    path('', include(router.urls)),
    path('exam-analytics/', ExamAnalyticsView.as_view(), name='exam-analytics'),
]
