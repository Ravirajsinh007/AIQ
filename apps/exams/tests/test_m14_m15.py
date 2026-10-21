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
    Batch,
    Department,
    Program,
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
from apps.exams.models import ExamAttempt, ExamSchedule


class RevaluationAndAnalyticsTests(APITestCase):
    def setUp(self):
        now = timezone.now()
        self.institute = Institute.objects.create(code='RVA', name='Revaluation Institute')
        self.admin = User.objects.create_user(
            email='exam-admin@rva.edu', password='AdminPass123!', is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.admin, institute=self.institute, role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.student = User.objects.create_user(
            email='student@rva.edu', password='StudentPass123!', is_verified=True
        )
        self.membership = UserInstituteMembership.objects.create(
            user=self.student, institute=self.institute, role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
        department = Department.objects.create(
            institute=self.institute, code='CS', name='Computer Science'
        )
        program = Program.objects.create(
            institute=self.institute, department=department, code='BSC', name='BSc',
            duration_years=3, total_semesters=6,
        )
        semester = Semester.objects.create(program=program, semester_number=1, label='S1')
        batch = Batch.objects.create(
            institute=self.institute, program=program, name='2026', admission_year=2026
        )
        section = Section.objects.create(batch=batch, name='A')
        subject = Subject.objects.create(
            institute=self.institute, department=department, code='CS101', name='Foundations'
        )
        ProgramSemesterSubject.objects.create(
            program=program, semester=semester, subject=subject
        )
        self.placement = StudentAcademicPlacement.objects.create(
            student=self.membership, program=program, batch=batch, semester=semester,
            section=section,
        )
        academic_year = AcademicYear.objects.create(
            institute=self.institute, label='2026-27', start_date=now.date(),
            end_date=(now + timedelta(days=365)).date(),
        )
        blueprint = PaperBlueprint.objects.create(
            institute=self.institute, title='Test Blueprint', subject=subject,
            academic_year=academic_year, semester=semester, program=program,
            total_marks=Decimal('2.00'), duration_minutes=60, status=BlueprintStatus.ACTIVE,
        )
        paper = GeneratedPaper.objects.create(
            institute=self.institute, blueprint=blueprint, title='Test Paper',
            subject=subject, total_marks=Decimal('2.00'), duration_minutes=60,
            status=GeneratedPaperStatus.COMPLETED, workflow_status=PaperWorkflowStatus.RELEASED,
        )
        self.question = GeneratedPaperQuestion.objects.create(
            paper=paper, section_name='A', section_order=1, question_number=1,
            question_version=1, question_type='mcq', question_text='Question',
            marks=Decimal('2.00'), negative_marks=Decimal('0.50'), difficulty='easy',
            bloom_taxonomy='remember',
            options_snapshot=[
                {'option_key': 'A', 'option_text': 'Correct', 'is_correct': True},
                {'option_key': 'B', 'option_text': 'Incorrect', 'is_correct': False},
            ],
        )
        self.exam = ExamSchedule.objects.create(
            institute=self.institute, paper=paper, batch=batch, section=section,
            starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1),
            published=True, created_by=self.admin,
        )
        self.client.force_authenticate(self.student)

    def _submit_final_attempt(self):
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
        return attempt['id']

    def test_revaluation_window_decision_history_and_mark_correction(self):
        now = timezone.now()
        self.exam.revaluation_opens_at = now - timedelta(minutes=1)
        self.exam.revaluation_closes_at = now + timedelta(minutes=30)
        self.exam.save()
        attempt_id = self._submit_final_attempt()
        response = self.client.post(
            reverse('revaluation-request-list'),
            {'attempt': attempt_id, 'question': str(self.question.pk), 'reason': 'Please recheck.'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        request_id = response.data['id']
        duplicate = self.client.post(
            reverse('revaluation-request-list'),
            {'attempt': attempt_id, 'question': str(self.question.pk), 'reason': 'Second request.'},
            format='json',
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(self.admin)
        decision = self.client.post(
            reverse('revaluation-request-decide', kwargs={'pk': request_id}),
            {'decision': 'approved', 'comment': 'Rechecked against the released rubric.',
             'corrected_marks': '1.50'},
            format='json',
        )
        self.assertEqual(decision.status_code, status.HTTP_200_OK, decision.data)
        self.assertEqual(len(decision.data['decisions']), 1)
        self.client.force_authenticate(self.student)
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt_id}))
        self.assertEqual(result.status_code, status.HTTP_200_OK)
        self.assertEqual(result.data['marks_awarded'], '1.50')

    def test_revaluation_requires_configured_open_window_and_student_ownership(self):
        attempt_id = self._submit_final_attempt()
        response = self.client.post(
            reverse('revaluation-request-list'),
            {'attempt': attempt_id, 'question': str(self.question.pk), 'reason': 'Recheck.'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        other = User.objects.create_user(email='other@rva.edu', password='OtherPass123!')
        self.client.force_authenticate(other)
        response = self.client.post(
            reverse('revaluation-request-list'),
            {'attempt': attempt_id, 'question': str(self.question.pk), 'reason': 'Recheck.'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_grievance_has_separate_review_without_changing_marks(self):
        now = timezone.now()
        self.exam.revaluation_opens_at = now - timedelta(minutes=1)
        self.exam.revaluation_closes_at = now + timedelta(minutes=30)
        self.exam.save()
        attempt_id = self._submit_final_attempt()
        response = self.client.post(
            reverse('exam-grievance-list'),
            {'attempt': attempt_id, 'reason': 'Exam delivery issue.'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        grievance_id = response.data['id']
        self.client.force_authenticate(self.admin)
        decision = self.client.post(
            reverse('exam-grievance-decide', kwargs={'pk': grievance_id}),
            {'decision': 'approved', 'comment': 'Issue reviewed and recorded.'},
            format='json',
        )
        self.assertEqual(decision.status_code, status.HTTP_200_OK, decision.data)
        self.assertEqual(len(decision.data['decisions']), 1)
        self.client.force_authenticate(self.student)
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt_id}))
        self.assertEqual(result.data['marks_awarded'], '2.00')

    def test_exam_analytics_excludes_unfinalized_results_and_requires_manager(self):
        final_attempt_id = self._submit_final_attempt()
        another_student = User.objects.create_user(
            email='second@rva.edu', password='StudentPass123!'
        )
        another_membership = UserInstituteMembership.objects.create(
            user=another_student, institute=self.institute, role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
        StudentAcademicPlacement.objects.create(
            student=another_membership, program=self.placement.program, batch=self.placement.batch,
            semester=self.placement.semester, section=self.placement.section,
        )
        ExamAttempt.objects.create(exam=self.exam, placement=StudentAcademicPlacement.objects.get(
            student=another_membership
        ))
        response = self.client.get(
            reverse('exam-analytics'), {'exam': str(self.exam.pk)}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.admin)
        response = self.client.get(
            reverse('exam-analytics'), {'exam': str(self.exam.pk)}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        analytics = response.data[0]
        self.assertEqual(analytics['attempt_count'], 2)
        self.assertEqual(analytics['in_progress_attempt_count'], 1)
        self.assertEqual(analytics['finalized_result_count'], 1)
        self.assertEqual(analytics['average_marks'], Decimal('2.00'))
        self.assertNotIn('student', analytics)
