from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DepartmentViewSet,
    ProgramViewSet,
    AcademicYearViewSet,
    SemesterViewSet,
    BatchViewSet,
    SectionViewSet,
    SubjectViewSet,
    ProgramSemesterSubjectViewSet,
    UnitViewSet,
    TopicViewSet,
    LearningOutcomeViewSet,
    ProgramOutcomeViewSet,
    OutcomeAlignmentViewSet,
    AssessmentOutcomeMappingViewSet,
    SyllabusMappingViewSet,
    TeacherAssignmentViewSet,
    StudentAcademicPlacementViewSet,
    StudentProgressionView,
    OutcomeAttainmentView,
    LearningSupportRecommendationsView,
    StudentRiskIndicatorsView,
    InstituteAdminDashboardView,
)

router = DefaultRouter()
router.register(r'departments', DepartmentViewSet, basename='department')
router.register(r'programs', ProgramViewSet, basename='program')
router.register(r'academic-years', AcademicYearViewSet, basename='academic-year')
router.register(r'semesters', SemesterViewSet, basename='semester')
router.register(r'batches', BatchViewSet, basename='batch')
router.register(r'sections', SectionViewSet, basename='section')
router.register(r'subjects', SubjectViewSet, basename='subject')
router.register(r'program-semester-subjects', ProgramSemesterSubjectViewSet, basename='program-semester-subject')
router.register(r'units', UnitViewSet, basename='unit')
router.register(r'topics', TopicViewSet, basename='topic')
router.register(r'learning-outcomes', LearningOutcomeViewSet, basename='learning-outcome')
router.register(r'program-outcomes', ProgramOutcomeViewSet, basename='program-outcome')
router.register(r'outcome-alignments', OutcomeAlignmentViewSet, basename='outcome-alignment')
router.register(r'assessment-outcome-mappings', AssessmentOutcomeMappingViewSet, basename='assessment-outcome-mapping')
router.register(r'syllabus-mappings', SyllabusMappingViewSet, basename='syllabus-mapping')
router.register(r'teacher-assignments', TeacherAssignmentViewSet, basename='teacher-assignment')
router.register(r'student-placements', StudentAcademicPlacementViewSet, basename='student-placement')

urlpatterns = [
    path('', include(router.urls)),
    path('institute-admin/dashboard/', InstituteAdminDashboardView.as_view(), name='institute-admin-dashboard'),
    path('student-placements/<uuid:placement_id>/progress/', StudentProgressionView.as_view(), name='student-placement-progress'),
    path('outcome-attainment/', OutcomeAttainmentView.as_view(), name='outcome-attainment'),
    path('learning-support/recommendations/', LearningSupportRecommendationsView.as_view(), name='learning-support-recommendations'),
    path('risk-indicators/', StudentRiskIndicatorsView.as_view(), name='student-risk-indicators'),
]
