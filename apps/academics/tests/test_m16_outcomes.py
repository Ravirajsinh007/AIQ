from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    Institute,
    MembershipStatus,
    RoleChoices,
    User,
    UserInstituteMembership,
)
from apps.academics.models import (
    AcademicYear,
    AssessmentOutcomeMapping,
    Batch,
    Department,
    LearningOutcome,
    OutcomeAlignment,
    Program,
    ProgramOutcome,
    ProgramSemesterSubject,
    Section,
    Semester,
    StudentAcademicPlacement,
    Subject,
)
from apps.blueprints.models import (
    BlueprintStatus,
    GeneratedPaper,
    GeneratedPaperQuestion,
    GeneratedPaperStatus,
    PaperBlueprint,
    PaperWorkflowStatus,
)
from apps.exams.models import ExamSchedule


class CourseOutcomeAttainmentTests(APITestCase):
    def setUp(self):
        now = timezone.now()
        self.institute = Institute.objects.create(code='OUT', name='Outcomes Institute')
        self.admin = User.objects.create_user(
            email='admin@out.edu', password='AdminPass123!', is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.admin, institute=self.institute, role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.student = User.objects.create_user(
            email='student@out.edu', password='StudentPass123!', is_verified=True
        )
        membership = UserInstituteMembership.objects.create(
            user=self.student, institute=self.institute, role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
        department = Department.objects.create(
            institute=self.institute, code='ENG', name='Engineering'
        )
        self.program = Program.objects.create(
            institute=self.institute, department=department, code='BE', name='Engineering',
            duration_years=4, total_semesters=8,
        )
        semester = Semester.objects.create(
            program=self.program, semester_number=1, label='Semester 1'
        )
        batch = Batch.objects.create(
            institute=self.institute, program=self.program, name='2026', admission_year=2026
        )
        section = Section.objects.create(batch=batch, name='A')
        self.subject = Subject.objects.create(
            institute=self.institute, department=department, code='EE101', name='Circuits'
        )
        ProgramSemesterSubject.objects.create(
            program=self.program, semester=semester, subject=self.subject
        )
        placement = StudentAcademicPlacement.objects.create(
            student=membership, program=self.program, batch=batch, semester=semester,
            section=section,
        )
        academic_year = AcademicYear.objects.create(
            institute=self.institute, label='2026-27', start_date=now.date(),
            end_date=(now + timedelta(days=365)).date(),
        )
        blueprint = PaperBlueprint.objects.create(
            institute=self.institute, title='Circuits Blueprint', subject=self.subject,
            academic_year=academic_year, semester=semester, program=self.program,
            total_marks=Decimal('4.00'), duration_minutes=60, status=BlueprintStatus.ACTIVE,
        )
        paper = GeneratedPaper.objects.create(
            institute=self.institute, blueprint=blueprint, title='Circuits Exam',
            subject=self.subject, total_marks=Decimal('4.00'), duration_minutes=60,
            status=GeneratedPaperStatus.COMPLETED, workflow_status=PaperWorkflowStatus.RELEASED,
        )
        self.question = GeneratedPaperQuestion.objects.create(
            paper=paper, section_name='A', section_order=1, question_number=1,
            question_version=1, question_type='mcq', question_text='Question',
            marks=Decimal('4.00'), difficulty='easy', bloom_taxonomy='apply',
            options_snapshot=[
                {'option_key': 'A', 'option_text': 'Correct', 'is_correct': True},
                {'option_key': 'B', 'option_text': 'Other', 'is_correct': False},
            ],
        )
        self.exam = ExamSchedule.objects.create(
            institute=self.institute, paper=paper, batch=batch, section=section,
            starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1),
            published=True, created_by=self.admin,
        )
        self.learning_outcome = LearningOutcome.objects.create(
            subject=self.subject, code='CO1', description='Analyze circuits.'
        )
        self.program_outcome = ProgramOutcome.objects.create(
            program=self.program, code='PO1', description='Apply engineering knowledge.'
        )
        self.client.force_authenticate(self.admin)
        self.placement = placement

    def test_mappings_and_attainment_evidence_use_final_exam_marks(self):
        alignment = OutcomeAlignment.objects.create(
            program_outcome=self.program_outcome, learning_outcome=self.learning_outcome
        )
        mapping = AssessmentOutcomeMapping.objects.create(
            paper_question=self.question, learning_outcome=self.learning_outcome
        )
        self.assertIsNotNone(alignment.pk)
        self.assertIsNotNone(mapping.pk)
        self.client.force_authenticate(self.student)
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.pk}), {}, format='json'
        ).data
        self.client.put(
            reverse('exam-attempt-answers', kwargs={'pk': attempt['id']}),
            {'question': str(self.question.pk), 'response': 'A'},
            format='json',
        )
        self.assertEqual(
            self.client.post(
                reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}),
                {}, format='json',
            ).status_code,
            status.HTTP_200_OK,
        )

        self.client.force_authenticate(self.admin)
        response = self.client.get(
            reverse('outcome-attainment'),
            {'program': str(self.program.pk), 'subject': str(self.subject.pk)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        outcome = response.data['course_outcomes'][0]
        self.assertEqual(outcome['earned_marks_total'], Decimal('4.00'))
        self.assertEqual(outcome['available_marks_total'], Decimal('4.00'))
        self.assertEqual(outcome['program_outcomes'], [str(self.program_outcome.pk)])
        self.assertIsNone(outcome['attainment_value'])
        self.assertEqual(response.data['attainment_calculation'], 'unresolved')

    def test_outcome_alignment_requires_program_curriculum_scope(self):
        other_subject = Subject.objects.create(
            institute=self.institute, code='EE202', name='Signals'
        )
        other_outcome = LearningOutcome.objects.create(
            subject=other_subject, code='CO1', description='Analyze signals.'
        )
        response = self.client.post(
            reverse('outcome-alignment-list'),
            {
                'program_outcome': str(self.program_outcome.pk),
                'learning_outcome': str(other_outcome.pk),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_students_cannot_access_outcome_attainment_and_cross_tenant_mapping(self):
        other_institute = Institute.objects.create(code='OTHER', name='Other Institute')
        other_department = Department.objects.create(
            institute=other_institute, code='OTH', name='Other'
        )
        other_program = Program.objects.create(
            institute=other_institute, department=other_department, code='OTH',
            name='Other Program', duration_years=4, total_semesters=8,
        )
        response = self.client.post(
            reverse('program-outcome-list'),
            {
                'program': str(other_program.pk),
                'code': 'PO-X',
                'description': 'Cross-tenant outcome',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('outcome-attainment'), {'program': str(self.program.pk)}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_learning_support_uses_final_result_gap_and_existing_course_materials(self):
        from apps.ai_generation.models import (
            DocumentProcessingStatus,
            DocumentType,
            SourceDocument,
        )
        from apps.academics.models import AssessmentOutcomeMapping

        AssessmentOutcomeMapping.objects.create(
            paper_question=self.question, learning_outcome=self.learning_outcome
        )
        SourceDocument.objects.create(
            institute=self.institute,
            subject=self.subject,
            title='Circuits notes',
            file='source_materials/circuits.pdf',
            file_type=DocumentType.PDF,
            processing_status=DocumentProcessingStatus.COMPLETED,
        )
        self.client.force_authenticate(self.student)
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.pk}), {}, format='json'
        ).data
        self.client.put(
            reverse('exam-attempt-answers', kwargs={'pk': attempt['id']}),
            {'question': str(self.question.pk), 'response': 'B'},
            format='json',
        )
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}),
            {}, format='json',
        )
        response = self.client.get(reverse('learning-support-recommendations'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['ai_generated'])
        self.assertEqual(response.data['final_assessment_count'], 1)
        self.assertEqual(len(response.data['recommendations']), 1)
        recommendation = response.data['recommendations'][0]
        self.assertEqual(recommendation['course_outcome_code'], 'CO1')
        self.assertEqual(len(recommendation['materials']), 1)

    def test_risk_indicators_are_manager_only_and_unclassified_without_rules(self):
        self.client.force_authenticate(self.student)
        response = self.client.get(
            reverse('student-risk-indicators'),
            {'institute': str(self.institute.pk)},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.pk}), {}, format='json'
        ).data
        self.client.put(
            reverse('exam-attempt-answers', kwargs={'pk': attempt['id']}),
            {'question': str(self.question.pk), 'response': 'A'},
            format='json',
        )
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}),
            {}, format='json',
        )
        self.client.force_authenticate(self.admin)
        response = self.client.get(
            reverse('student-risk-indicators'),
            {'institute': str(self.institute.pk)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['classification_method'], 'unresolved')
        student_row = response.data['students'][0]
        self.assertIsNone(student_row['risk_classification'])
        self.assertEqual(student_row['assessment_status'], 'evidence_available')
        self.assertEqual(student_row['finalized_result_count'], 1)
        self.assertEqual(student_row['earned_marks_total'], Decimal('4.00'))
