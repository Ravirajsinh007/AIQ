from decimal import Decimal
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets, status
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from drf_spectacular.utils import extend_schema, OpenApiResponse
from apps.accounts.permissions import EnforcePasswordChange
from .permissions import IsInstituteAcademicAdmin
from apps.accounts.models import MembershipStatus, RoleChoices, UserInstituteMembership
from .models import (
    Department,
    Program,
    AcademicYear,
    Semester,
    Batch,
    Section,
    Subject,
    ProgramSemesterSubject,
    Unit,
    Topic,
    LearningOutcome,
    ProgramOutcome,
    OutcomeAlignment,
    AssessmentOutcomeMapping,
    PlacementStatus,
    SyllabusMapping,
    TeacherAssignment,
    StudentAcademicPlacement,
)
from .serializers import (
    DepartmentSerializer,
    ProgramSerializer,
    AcademicYearSerializer,
    SemesterSerializer,
    BatchSerializer,
    SectionSerializer,
    SubjectSerializer,
    ProgramSemesterSubjectSerializer,
    UnitSerializer,
    TopicSerializer,
    LearningOutcomeSerializer,
    ProgramOutcomeSerializer,
    OutcomeAlignmentSerializer,
    AssessmentOutcomeMappingSerializer,
    SyllabusMappingSerializer,
    TeacherAssignmentSerializer,
    StudentAcademicPlacementSerializer,
    StudentProgressionSerializer,
)


class BaseAcademicViewSet(viewsets.ModelViewSet):
    """
    Base viewset enforcing authentication, password change verification,
    and academic admin permissions for write operations.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAcademicAdmin]

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        self._audit(instance, 'created')

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        self._audit(instance, 'updated')

    @transaction.atomic
    def perform_destroy(self, instance):
        self._audit(instance, 'deleted')
        instance.delete()

    def _audit(self, instance, verb):
        from apps.audit.services import institute_for_resource, record_audit_event

        record_audit_event(
            action=f'academic.{instance._meta.model_name}.{verb}',
            resource_type=instance._meta.label_lower,
            resource_id=instance.pk,
            actor=self.request.user,
            institute=institute_for_resource(instance),
        )


class DepartmentViewSet(BaseAcademicViewSet):
    serializer_class = DepartmentSerializer
    filterset_fields = ['institute', 'status']
    search_fields = ['code', 'name']
    ordering_fields = ['name', 'code', 'created_at']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Department.objects.all().select_related('institute')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Department.objects.filter(institute_id__in=user_institutes).select_related('institute')


class ProgramViewSet(BaseAcademicViewSet):
    serializer_class = ProgramSerializer
    filterset_fields = ['institute', 'department', 'qualification_type', 'status']
    search_fields = ['code', 'name']
    ordering_fields = ['name', 'code', 'created_at']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Program.objects.all().select_related('institute', 'department')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Program.objects.filter(institute_id__in=user_institutes).select_related('institute', 'department')


class AcademicYearViewSet(BaseAcademicViewSet):
    serializer_class = AcademicYearSerializer
    filterset_fields = ['institute', 'is_current', 'status']
    search_fields = ['label']
    ordering_fields = ['start_date', 'label']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return AcademicYear.objects.all().select_related('institute')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return AcademicYear.objects.filter(institute_id__in=user_institutes).select_related('institute')


class SemesterViewSet(BaseAcademicViewSet):
    serializer_class = SemesterSerializer
    filterset_fields = ['program', 'status']
    search_fields = ['label']
    ordering_fields = ['semester_number', 'label']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Semester.objects.all().select_related('program')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Semester.objects.filter(program__institute_id__in=user_institutes).select_related('program')


class BatchViewSet(BaseAcademicViewSet):
    serializer_class = BatchSerializer
    filterset_fields = ['institute', 'program', 'admission_year', 'status']
    search_fields = ['name']
    ordering_fields = ['admission_year', 'name']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Batch.objects.all().select_related('institute', 'program')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Batch.objects.filter(institute_id__in=user_institutes).select_related('institute', 'program')


class SectionViewSet(BaseAcademicViewSet):
    serializer_class = SectionSerializer
    filterset_fields = ['batch', 'status']
    search_fields = ['name']
    ordering_fields = ['name']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Section.objects.all().select_related('batch')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Section.objects.filter(batch__institute_id__in=user_institutes).select_related('batch')


class SubjectViewSet(BaseAcademicViewSet):
    serializer_class = SubjectSerializer
    filterset_fields = ['institute', 'department', 'status']
    search_fields = ['code', 'name']
    ordering_fields = ['code', 'name']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Subject.objects.all().select_related('institute', 'department')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Subject.objects.filter(institute_id__in=user_institutes).select_related('institute', 'department')


class ProgramSemesterSubjectViewSet(BaseAcademicViewSet):
    serializer_class = ProgramSemesterSubjectSerializer
    filterset_fields = ['program', 'semester', 'subject', 'is_mandatory']
    ordering_fields = ['program', 'semester']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return ProgramSemesterSubject.objects.all().select_related('program', 'semester', 'subject')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return ProgramSemesterSubject.objects.filter(program__institute_id__in=user_institutes).select_related('program', 'semester', 'subject')


class UnitViewSet(BaseAcademicViewSet):
    serializer_class = UnitSerializer
    filterset_fields = ['subject']
    search_fields = ['title']
    ordering_fields = ['unit_number']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Unit.objects.all().select_related('subject')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Unit.objects.filter(subject__institute_id__in=user_institutes).select_related('subject')


class TopicViewSet(BaseAcademicViewSet):
    serializer_class = TopicSerializer
    filterset_fields = ['unit']
    search_fields = ['title']
    ordering_fields = ['order', 'title']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return Topic.objects.all().select_related('unit__subject')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return Topic.objects.filter(unit__subject__institute_id__in=user_institutes).select_related('unit__subject')


class LearningOutcomeViewSet(BaseAcademicViewSet):
    serializer_class = LearningOutcomeSerializer
    filterset_fields = ['subject', 'category']
    search_fields = ['code', 'description']
    ordering_fields = ['code']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return LearningOutcome.objects.all().select_related('subject')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return LearningOutcome.objects.filter(subject__institute_id__in=user_institutes).select_related('subject')


class ProgramOutcomeViewSet(BaseAcademicViewSet):
    serializer_class = ProgramOutcomeSerializer
    filterset_fields = ['program']
    search_fields = ['code', 'description']
    ordering_fields = ['code', 'created_at']

    def get_queryset(self):
        outcomes = ProgramOutcome.objects.select_related('program')
        if self.request.user.is_platform_admin:
            return outcomes
        institute_ids = self.request.user.memberships.filter(
            status=MembershipStatus.ACTIVE
        ).values_list('institute_id', flat=True)
        return outcomes.filter(program__institute_id__in=institute_ids)


class OutcomeAlignmentViewSet(BaseAcademicViewSet):
    serializer_class = OutcomeAlignmentSerializer
    filterset_fields = ['program_outcome', 'learning_outcome']

    def get_queryset(self):
        alignments = OutcomeAlignment.objects.select_related(
            'program_outcome__program', 'learning_outcome__subject'
        )
        if self.request.user.is_platform_admin:
            return alignments
        institute_ids = self.request.user.memberships.filter(
            status=MembershipStatus.ACTIVE
        ).values_list('institute_id', flat=True)
        return alignments.filter(program_outcome__program__institute_id__in=institute_ids)


class AssessmentOutcomeMappingViewSet(BaseAcademicViewSet):
    serializer_class = AssessmentOutcomeMappingSerializer
    filterset_fields = ['paper_question', 'learning_outcome']

    def get_queryset(self):
        mappings = AssessmentOutcomeMapping.objects.select_related(
            'paper_question__paper__subject', 'learning_outcome__subject'
        )
        if self.request.user.is_platform_admin:
            return mappings
        institute_ids = self.request.user.memberships.filter(
            status=MembershipStatus.ACTIVE
        ).values_list('institute_id', flat=True)
        return mappings.filter(
            paper_question__paper__institute_id__in=institute_ids
        )


class SyllabusMappingViewSet(BaseAcademicViewSet):
    serializer_class = SyllabusMappingSerializer
    filterset_fields = ['subject', 'academic_year', 'status']
    search_fields = ['syllabus_reference']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return SyllabusMapping.objects.all().select_related('subject', 'academic_year')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        return SyllabusMapping.objects.filter(subject__institute_id__in=user_institutes).select_related('subject', 'academic_year')


class TeacherAssignmentViewSet(BaseAcademicViewSet):
    serializer_class = TeacherAssignmentSerializer
    filterset_fields = ['teacher', 'subject', 'academic_year', 'status']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return TeacherAssignment.objects.all().select_related('teacher__user', 'subject', 'academic_year')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        # Teachers can view their own assignments; Admins see all for their institute
        is_admin = user.memberships.filter(role='institute_admin').exists()
        qs = TeacherAssignment.objects.filter(subject__institute_id__in=user_institutes).select_related('teacher__user', 'subject', 'academic_year')
        if not is_admin:
            qs = qs.filter(teacher__user=user)
        return qs


class StudentAcademicPlacementViewSet(BaseAcademicViewSet):
    serializer_class = StudentAcademicPlacementSerializer
    filterset_fields = ['student', 'program', 'batch', 'semester', 'status']

    def get_queryset(self):
        user = self.request.user
        if user.is_platform_admin:
            return StudentAcademicPlacement.objects.all().select_related('student__user', 'program', 'batch', 'semester', 'section')
        user_institutes = user.memberships.values_list('institute_id', flat=True)
        is_admin = user.memberships.filter(role='institute_admin').exists()
        qs = StudentAcademicPlacement.objects.filter(program__institute_id__in=user_institutes).select_related('student__user', 'program', 'batch', 'semester', 'section')
        if not is_admin:
            qs = qs.filter(student__user=user)
        return qs


class StudentProgressionView(APIView):
    """
    Advances a student to the next academic semester while completing
    and preserving the past semester placement record for audit/history.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, IsInstituteAcademicAdmin]

    @extend_schema(
        summary="Progress Student to Next Semester",
        request=StudentProgressionSerializer,
        responses={201: StudentAcademicPlacementSerializer}
    )
    @transaction.atomic
    def post(self, request, placement_id):
        placement = get_object_or_404(StudentAcademicPlacement, id=placement_id)
        # Check permissions for this placement's institute
        if not request.user.is_platform_admin:
            has_perm = request.user.memberships.filter(
                institute_id=placement.program.institute_id,
                role='institute_admin'
            ).exists()
            if not has_perm:
                return Response(
                    {'error': {'message': 'Permission denied for this institute.'}},
                    status=status.HTTP_403_FORBIDDEN
                )

        serializer = StudentProgressionSerializer(data=request.data, context={'placement': placement})
        serializer.is_valid(raise_exception=True)
        new_placement = serializer.save()
        from apps.audit.services import record_audit_event

        record_audit_event(
            action='academic.student_placement.progressed',
            resource_type='student_academic_placement',
            resource_id=new_placement.pk,
            actor=request.user,
            institute=new_placement.program.institute,
        )
        return Response(
            StudentAcademicPlacementSerializer(new_placement).data,
            status=status.HTTP_201_CREATED
        )


class OutcomeAttainmentView(APIView):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]

    @extend_schema(
        summary='Retrieve outcome mappings and final-assessment evidence for a program',
        responses={200: dict},
    )
    def get(self, request):
        from apps.exams.models import ExamAttempt, ExamAttemptStatus
        from apps.exams.views import _result_for_attempt

        program_id = request.query_params.get('program')
        if not program_id:
            raise ValidationError({'program': 'This query parameter is required.'})
        program_id = serializers.UUIDField().run_validation(program_id)
        program = Program.objects.filter(pk=program_id).first()
        if program is None:
            raise NotFound('Program not found.')
        user = request.user
        if not user.is_platform_admin and not user.memberships.filter(
            institute_id=program.institute_id,
            status=MembershipStatus.ACTIVE,
        ).exists():
            raise NotFound('Program not found.')
        manager = user.is_platform_admin or user.memberships.filter(
            institute_id=program.institute_id,
            status=MembershipStatus.ACTIVE,
            role=RoleChoices.INSTITUTE_ADMIN,
        ).exists()
        if not manager and not user.is_platform_admin:
            manager = any(
                membership.role == RoleChoices.EXAM_STAFF
                and {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
                for membership in user.memberships.filter(
                    institute_id=program.institute_id, status=MembershipStatus.ACTIVE
                )
            )

        subject_ids = ProgramSemesterSubject.objects.filter(
            program=program
        ).values_list('subject_id', flat=True)
        if request.query_params.get('subject'):
            subject_id = serializers.UUIDField().run_validation(request.query_params['subject'])
            subject_ids = subject_ids.filter(subject_id=subject_id)
        if request.query_params.get('semester'):
            semester_id = serializers.UUIDField().run_validation(request.query_params['semester'])
            subject_ids = subject_ids.filter(semester_id=semester_id)
        subject_ids = list(subject_ids.distinct())
        if not subject_ids:
            raise ValidationError({'subject': 'No course subject matches this program scope.'})
        teacher_scope = []
        if not manager:
            assignments = TeacherAssignment.objects.filter(
                teacher__user=user,
                teacher__status=MembershipStatus.ACTIVE,
                status='active',
                subject_id__in=subject_ids,
                subject__institute_id=program.institute_id,
            ).values_list('subject_id', 'batch_id', 'section_id')
            teacher_scope = list(assignments)
            if not teacher_scope:
                raise PermissionDenied('Outcome reporting requires program management or a teaching assignment.')
            assigned_subject_ids = {scope[0] for scope in teacher_scope}
            subject_ids = [subject_id for subject_id in subject_ids if subject_id in assigned_subject_ids]
            teacher_scope = [
                scope for scope in teacher_scope if scope[0] in subject_ids
            ]

        batch_id = request.query_params.get('batch')
        if batch_id:
            batch_id = serializers.UUIDField().run_validation(batch_id)
        if batch_id and not program.batches.filter(pk=batch_id).exists():
            raise ValidationError({'batch': 'Batch must belong to the selected program.'})
        if batch_id and teacher_scope and not any(
            assigned_batch is None or str(assigned_batch) == batch_id
            for _subject, assigned_batch, _section in teacher_scope
        ):
            raise PermissionDenied('The requested batch is outside the teacher assignment.')

        mappings = list(AssessmentOutcomeMapping.objects.filter(
            learning_outcome__subject_id__in=subject_ids,
            paper_question__paper__subject_id__in=subject_ids,
        ).select_related('paper_question', 'learning_outcome'))
        question_outcomes = {}
        for mapping in mappings:
            question_outcomes.setdefault(mapping.paper_question_id, []).append(mapping.learning_outcome)
        evidence = {}
        attempts = ExamAttempt.objects.filter(
            status__in=(ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED),
            exam__batch__program=program,
            exam__paper__subject_id__in=subject_ids,
        )
        if batch_id:
            attempts = attempts.filter(exam__batch_id=batch_id)
        if teacher_scope:
            assignment_scope = Q(pk__in=[])
            for subject_id, assigned_batch, assigned_section in teacher_scope:
                scope = Q(exam__paper__subject_id=subject_id)
                if assigned_batch:
                    scope &= Q(exam__batch_id=assigned_batch)
                if assigned_section:
                    scope &= Q(exam__section_id=assigned_section)
                assignment_scope |= scope
            attempts = attempts.filter(assignment_scope)
        attempts = attempts.select_related(
            'exam__paper', 'placement__student'
        ).prefetch_related(
            'exam__paper__paper_questions', 'answers__evaluation',
            'handwritten_sheet__evaluations', 'revaluation_requests',
        )
        for attempt in attempts:
            result = _result_for_attempt(attempt)
            if not result['is_final']:
                continue
            for item in result['questions']:
                for outcome in question_outcomes.get(item['question'], []):
                    totals = evidence.setdefault(outcome.pk, {
                        'attempt_count': 0,
                        'earned_marks_total': Decimal('0.00'),
                        'available_marks_total': Decimal('0.00'),
                        'assessments': set(),
                    })
                    totals['attempt_count'] += 1
                    totals['earned_marks_total'] += item['marks_awarded']
                    totals['available_marks_total'] += item['max_marks']
                    totals['assessments'].add(str(attempt.exam_id))

        outcomes = LearningOutcome.objects.filter(subject_id__in=subject_ids).prefetch_related(
            'program_alignments__program_outcome'
        )
        outcome_rows = []
        for outcome in outcomes:
            totals = evidence.get(outcome.pk, {
                'attempt_count': 0,
                'earned_marks_total': Decimal('0.00'),
                'available_marks_total': Decimal('0.00'),
                'assessments': set(),
            })
            outcome_rows.append({
                'course_outcome': str(outcome.pk),
                'subject': str(outcome.subject_id),
                'code': outcome.code,
                'attempt_count': totals['attempt_count'],
                'earned_marks_total': totals['earned_marks_total'],
                'available_marks_total': totals['available_marks_total'],
                'assessment_ids': sorted(totals['assessments']),
                'program_outcomes': [
                    str(alignment.program_outcome_id)
                    for alignment in outcome.program_alignments.all()
                    if alignment.program_outcome.program_id == program.pk
                ],
                'attainment_value': None,
                'attainment_formula': None,
            })
        evidence_by_outcome = {
            row['course_outcome']: row for row in outcome_rows
        }
        program_outcome_rows = []
        for program_outcome in ProgramOutcome.objects.filter(
            program=program
        ).prefetch_related('course_alignments__learning_outcome'):
            aligned = [
                alignment.learning_outcome_id
                for alignment in program_outcome.course_alignments.all()
                if alignment.learning_outcome_id in evidence_by_outcome
            ]
            program_outcome_rows.append({
                'program_outcome': str(program_outcome.pk),
                'code': program_outcome.code,
                'aligned_course_outcomes': [
                    evidence_by_outcome[outcome_id] for outcome_id in aligned
                ],
                'attainment_value': None,
                'attainment_formula': None,
            })
        return Response({
            'program': str(program.pk),
            'scope': {
                'subjects': [str(subject_id) for subject_id in subject_ids],
                'batch': str(batch_id) if batch_id else None,
            },
            'course_outcomes': outcome_rows,
            'program_outcomes': program_outcome_rows,
            'attainment_calculation': 'unresolved',
        })


class LearningSupportRecommendationsView(APIView):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]

    @extend_schema(
        summary='Recommend existing course materials using the student’s final assessment evidence',
        responses={200: dict},
    )
    def get(self, request):
        from apps.ai_generation.models import DocumentProcessingStatus, SourceDocument
        from apps.academics.models import AssessmentOutcomeMapping
        from apps.exams.models import ExamAttempt, ExamAttemptStatus
        from apps.exams.views import _result_for_attempt

        memberships = request.user.memberships.filter(
            role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE
        )
        if request.query_params.get('institute'):
            institute_id = serializers.UUIDField().run_validation(request.query_params['institute'])
            memberships = memberships.filter(institute_id=institute_id)
        if not memberships.exists():
            raise PermissionDenied('Learning support is available to active student memberships only.')
        subject_id = request.query_params.get('subject')
        if subject_id:
            subject_id = serializers.UUIDField().run_validation(subject_id)
        attempts = ExamAttempt.objects.filter(
            placement__student__in=memberships,
            status__in=(ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED),
        )
        if subject_id:
            attempts = attempts.filter(exam__paper__subject_id=subject_id)
        attempts = attempts.select_related(
            'exam__paper', 'placement__student'
        ).prefetch_related(
            'exam__paper__paper_questions', 'answers__evaluation',
            'handwritten_sheet__evaluations', 'revaluation_requests',
        )
        evidence = {}
        final_attempt_ids = set()
        for attempt in attempts:
            result = _result_for_attempt(attempt)
            if not result['is_final']:
                continue
            final_attempt_ids.add(attempt.pk)
            for item in result['questions']:
                totals = evidence.setdefault(item['question'], {
                    'earned_marks': Decimal('0.00'),
                    'available_marks': Decimal('0.00'),
                    'subject_id': str(attempt.exam.paper.subject_id),
                })
                totals['earned_marks'] += item['marks_awarded']
                totals['available_marks'] += item['max_marks']
        question_ids = list(evidence)
        mappings = AssessmentOutcomeMapping.objects.filter(
            paper_question_id__in=question_ids
        ).select_related('learning_outcome__subject')
        outcomes = {}
        for mapping in mappings:
            totals = evidence[mapping.paper_question_id]
            outcome = outcomes.setdefault(mapping.learning_outcome_id, {
                'course_outcome': str(mapping.learning_outcome_id),
                'code': mapping.learning_outcome.code,
                'subject': str(mapping.learning_outcome.subject_id),
                'earned_marks': Decimal('0.00'),
                'available_marks': Decimal('0.00'),
                'source_questions': set(),
            })
            outcome['earned_marks'] += totals['earned_marks']
            outcome['available_marks'] += totals['available_marks']
            outcome['source_questions'].add(str(mapping.paper_question_id))

        institute_ids = memberships.values_list('institute_id', flat=True)
        subject_ids = {row['subject'] for row in outcomes.values()}
        materials = SourceDocument.objects.filter(
            institute_id__in=institute_ids,
            subject_id__in=subject_ids,
            processing_status=DocumentProcessingStatus.COMPLETED,
        ).select_related('subject', 'unit', 'topic')
        materials_by_subject = {}
        for document in materials:
            materials_by_subject.setdefault(str(document.subject_id), []).append({
                'id': str(document.pk),
                'title': document.title,
                'unit': document.unit.title if document.unit_id else None,
                'topic': document.topic.title if document.topic_id else None,
            })

        recommendations = []
        for outcome in outcomes.values():
            marks_not_earned = outcome['available_marks'] - outcome['earned_marks']
            if marks_not_earned <= 0:
                continue
            recommendations.append({
                'course_outcome': outcome['course_outcome'],
                'course_outcome_code': outcome['code'],
                'subject': outcome['subject'],
                'earned_marks': outcome['earned_marks'],
                'available_marks': outcome['available_marks'],
                'marks_not_earned': marks_not_earned,
                'basis': 'final_assessment_marks_not_earned',
                'source_questions': sorted(outcome['source_questions']),
                'materials': materials_by_subject.get(outcome['subject'], []),
                'materials_scope': 'subject-level; materials are not mapped directly to outcomes',
            })
        recommendations.sort(key=lambda row: row['marks_not_earned'], reverse=True)
        return Response({
            'recommendation_method': 'evidence_based_material_links',
            'ai_generated': False,
            'final_assessment_count': len(final_attempt_ids),
            'recommendations': recommendations,
            'status': (
                'insufficient_final_assessment_data' if not final_attempt_ids
                else 'missing_assessment_outcome_mappings' if not outcomes
                else 'evidence_available'
            ),
        })


class StudentRiskIndicatorsView(APIView):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]

    @extend_schema(
        summary='Retrieve institute-scoped student assessment evidence for authorized managers',
        responses={200: dict},
    )
    def get(self, request):
        from apps.exams.models import ExamAttempt, ExamAttemptStatus
        from apps.exams.permissions import is_exam_manager
        from apps.exams.views import _result_for_attempt

        institute_param = request.query_params.get('institute')
        if not institute_param:
            raise ValidationError({'institute': 'This query parameter is required.'})
        institute_id = serializers.UUIDField().run_validation(institute_param)
        if not is_exam_manager(request.user, institute_id):
            raise PermissionDenied('Risk indicators require exam management permission.')
        batch_id = request.query_params.get('batch')
        subject_id = request.query_params.get('subject')
        if batch_id:
            batch_id = serializers.UUIDField().run_validation(batch_id)
            if not Batch.objects.filter(pk=batch_id, institute_id=institute_id).exists():
                raise ValidationError({'batch': 'Batch must belong to the selected institute.'})
        if subject_id:
            subject_id = serializers.UUIDField().run_validation(subject_id)
            if not Subject.objects.filter(pk=subject_id, institute_id=institute_id).exists():
                raise ValidationError({'subject': 'Subject must belong to the selected institute.'})

        students = UserInstituteMembership.objects.filter(
            institute_id=institute_id,
            role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE,
            academic_placements__status=PlacementStatus.ACTIVE,
            academic_placements__effective_start_date__lte=timezone.localdate(),
        ).distinct().select_related('user')
        students = students.filter(
            Q(academic_placements__effective_end_date__isnull=True)
            | Q(academic_placements__effective_end_date__gte=timezone.localdate())
        )
        if batch_id:
            students = students.filter(academic_placements__batch_id=batch_id)
        if subject_id:
            students = students.filter(
                academic_placements__program__semester_subjects__subject_id=subject_id
            )

        attempts = ExamAttempt.objects.filter(
            placement__student__in=students,
            exam__institute_id=institute_id,
            placement__status=PlacementStatus.ACTIVE,
        )
        if batch_id:
            attempts = attempts.filter(exam__batch_id=batch_id)
        if subject_id:
            attempts = attempts.filter(exam__paper__subject_id=subject_id)
        attempts = attempts.select_related(
            'exam__paper', 'placement__student'
        ).prefetch_related(
            'exam__paper__paper_questions', 'answers__evaluation',
            'handwritten_sheet__evaluations', 'revaluation_requests',
        )

        indicators = {}
        for attempt in attempts:
            student_id = str(attempt.placement.student_id)
            row = indicators.setdefault(student_id, {
                'student_membership': student_id,
                'completed_attempt_count': 0,
                'in_progress_attempt_count': 0,
                'pending_grading_count': 0,
                'finalized_result_count': 0,
                'earned_marks_total': Decimal('0.00'),
                'available_marks_total': Decimal('0.00'),
            })
            if attempt.status == ExamAttemptStatus.IN_PROGRESS:
                row['in_progress_attempt_count'] += 1
                continue
            if attempt.status not in (
                ExamAttemptStatus.SUBMITTED, ExamAttemptStatus.AUTO_SUBMITTED
            ):
                continue
            row['completed_attempt_count'] += 1
            result = _result_for_attempt(attempt)
            if not result['is_final']:
                row['pending_grading_count'] += 1
                continue
            row['finalized_result_count'] += 1
            row['earned_marks_total'] += result['marks_awarded']
            row['available_marks_total'] += result['max_marks']

        data = []
        for membership in students:
            row = indicators.get(str(membership.pk), {
                'student_membership': str(membership.pk),
                'completed_attempt_count': 0,
                'in_progress_attempt_count': 0,
                'pending_grading_count': 0,
                'finalized_result_count': 0,
                'earned_marks_total': Decimal('0.00'),
                'available_marks_total': Decimal('0.00'),
            })
            row.update({
                'student_name': membership.user.full_name,
                'risk_classification': None,
                'assessment_status': (
                    'evidence_available' if row['finalized_result_count']
                    else 'insufficient_data'
                ),
            })
            data.append(row)
        return Response({
            'institute': str(institute_id),
            'scope': {'batch': str(batch_id) if batch_id else None,
                      'subject': str(subject_id) if subject_id else None},
            'classification_method': 'unresolved',
            'unresolved_rule': (
                'The project specification defines no risk formula, feature weights, '
                'minimum-data rule, or classification thresholds.'
            ),
            'students': data,
        })
