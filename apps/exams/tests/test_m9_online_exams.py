from datetime import timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django.core.management import call_command
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Institute, MembershipStatus, RoleChoices, User, UserInstituteMembership
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
from apps.audit.models import AuditEvent
from apps.blueprints.models import (
    BlueprintStatus,
    GeneratedPaper,
    GeneratedPaperQuestion,
    GeneratedPaperStatus,
    PaperWorkflowStatus,
    PaperBlueprint,
)
from apps.exams.models import (
    CodingSubmission,
    ExamActivityEvent,
    ExamAnswerEvaluation,
    ExamAttempt,
    ExamAttemptStatus,
    ExamIntegrityFlag,
    ExamSchedule,
    HandwrittenAnswerSheet,
)


class OnlineExamDeliveryTests(APITestCase):
    def setUp(self):
        now = timezone.now()
        self.institute = Institute.objects.create(code='EXAM', name='Exam Institute')
        self.admin = User.objects.create_user(email='admin@exam.edu', password='AdminPass123!', is_verified=True)
        self.admin_membership = UserInstituteMembership.objects.create(
            user=self.admin,
            institute=self.institute,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.student = User.objects.create_user(email='student@exam.edu', password='StudentPass123!', is_verified=True)
        self.student_membership = UserInstituteMembership.objects.create(
            user=self.student,
            institute=self.institute,
            role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
        self.department = Department.objects.create(institute=self.institute, code='CSE', name='Computing')
        self.program = Program.objects.create(
            institute=self.institute,
            department=self.department,
            code='BSC-CS',
            name='Computer Science',
            duration_years=3,
            total_semesters=6,
        )
        self.semester = Semester.objects.create(
            program=self.program, semester_number=1, label='Semester 1'
        )
        self.batch = Batch.objects.create(
            institute=self.institute, program=self.program, name='2026 Batch', admission_year=2026
        )
        self.section = Section.objects.create(batch=self.batch, name='A')
        self.subject = Subject.objects.create(
            institute=self.institute, department=self.department, code='CS101', name='Foundations'
        )
        ProgramSemesterSubject.objects.create(
            program=self.program, semester=self.semester, subject=self.subject
        )
        self.placement = StudentAcademicPlacement.objects.create(
            student=self.student_membership,
            program=self.program,
            batch=self.batch,
            semester=self.semester,
            section=self.section,
        )
        self.academic_year = AcademicYear.objects.create(
            institute=self.institute,
            label='2026-2027',
            start_date=now.date(),
            end_date=(now + timedelta(days=365)).date(),
        )
        self.blueprint = PaperBlueprint.objects.create(
            institute=self.institute,
            title='Foundations Paper',
            subject=self.subject,
            academic_year=self.academic_year,
            semester=self.semester,
            program=self.program,
            total_marks=Decimal('2.00'),
            duration_minutes=60,
            status=BlueprintStatus.ACTIVE,
        )
        self.paper = GeneratedPaper.objects.create(
            institute=self.institute,
            blueprint=self.blueprint,
            title='Foundations Exam',
            subject=self.subject,
            total_marks=Decimal('2.00'),
            duration_minutes=60,
            status=GeneratedPaperStatus.COMPLETED,
            workflow_status=PaperWorkflowStatus.RELEASED,
        )
        self.question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='A',
            section_order=1,
            question_number=1,
            question_version=1,
            question_type='mcq',
            question_text='Select the correct answer.',
            marks=Decimal('2.00'),
            difficulty='easy',
            bloom_taxonomy='remember',
            options_snapshot=[
                {'option_key': 'A', 'option_text': 'Correct', 'order': 1, 'is_correct': True},
                {'option_key': 'B', 'option_text': 'Other', 'order': 2, 'is_correct': False},
            ],
            rubric_snapshot=[{'criterion': 'private', 'max_marks': '2.00'}],
            provenance_snapshot=[{'excerpt': 'private source'}],
        )
        self.exam = ExamSchedule.objects.create(
            institute=self.institute,
            paper=self.paper,
            batch=self.batch,
            section=self.section,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=59),
            published=True,
            created_by=self.admin,
        )
        self.client.force_authenticate(self.student)

    def test_start_delivers_sanitized_questions_saves_and_submits_idempotently(self):
        start_response = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        )
        self.assertEqual(start_response.status_code, status.HTTP_200_OK)
        attempt_id = start_response.data['id']

        question_response = self.client.get(reverse('exam-questions', kwargs={'pk': self.exam.id}))
        self.assertEqual(question_response.status_code, status.HTTP_200_OK)
        delivered = question_response.data[0]
        self.assertEqual(delivered['id'], str(self.question.id))
        self.assertNotIn('rubric_snapshot', delivered)
        self.assertNotIn('provenance_snapshot', delivered)
        self.assertNotIn('is_correct', delivered['options'][0])

        answer_url = reverse('exam-attempt-answers', kwargs={'pk': attempt_id})
        answer_response = self.client.put(
            answer_url,
            {'question': str(self.question.id), 'response': 'A'},
            format='json',
        )
        self.assertEqual(answer_response.status_code, status.HTTP_200_OK)
        self.assertEqual(answer_response.data['response'], 'A')

        submit_url = reverse('exam-attempt-submit', kwargs={'pk': attempt_id})
        first_submit = self.client.post(submit_url, {}, format='json')
        second_submit = self.client.post(submit_url, {}, format='json')
        self.assertEqual(first_submit.status_code, status.HTTP_200_OK)
        self.assertEqual(second_submit.status_code, status.HTTP_200_OK)
        self.assertEqual(first_submit.data['status'], ExamAttemptStatus.SUBMITTED)
        self.assertEqual(second_submit.data['status'], ExamAttemptStatus.SUBMITTED)
        self.assertEqual(
            self.client.put(
                answer_url,
                {'question': str(self.question.id), 'response': 'B'},
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_another_student_cannot_read_or_change_attempt(self):
        attempt_response = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        )
        attempt_id = attempt_response.data['id']
        another_student = User.objects.create_user(
            email='other@exam.edu', password='OtherPass123!', is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=another_student,
            institute=self.institute,
            role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE,
        )
        self.client.force_authenticate(another_student)

        response = self.client.get(reverse('exam-attempt-detail', kwargs={'pk': attempt_id}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        answer_response = self.client.put(
            reverse('exam-attempt-answers', kwargs={'pk': attempt_id}),
            {'question': str(self.question.id), 'response': 'A'},
            format='json',
        )
        self.assertEqual(answer_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_client_signals_are_labeled_and_flag_requires_manager_review(self):
        start_response = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        )
        attempt_id = start_response.data['id']
        event_url = reverse('exam-attempt-events', kwargs={'pk': attempt_id})
        for _ in range(5):
            response = self.client.post(
                event_url,
                {'event_type': 'visibility_changed', 'metadata': {'state': 'hidden'}},
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        flag = ExamIntegrityFlag.objects.get(attempt_id=attempt_id)
        self.assertIn('client-reported', flag.explanation)
        self.assertEqual(
            ExamActivityEvent.objects.filter(
                attempt_id=attempt_id, source='client_reported'
            ).count(),
            5,
        )
        self.client.force_authenticate(self.admin)
        review_url = reverse('integrity-flag-review', kwargs={'pk': flag.id})
        review_response = self.client.post(
            review_url,
            {'status': 'reviewed', 'review_decision': 'Reviewed; signal alone is not proof.'},
            format='json',
        )
        self.assertEqual(review_response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertEqual(flag.status, 'reviewed')
        self.assertEqual(flag.reviewed_by, self.admin)

    def test_deadline_command_auto_submits_using_server_timestamps(self):
        start_response = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        )
        attempt_id = start_response.data['id']
        self.exam.ends_at = timezone.now() - timedelta(seconds=1)
        self.exam.save(update_fields=['ends_at', 'updated_at'])

        call_command('process_exam_deadlines', verbosity=0)

        attempt = ExamAttempt.objects.get(pk=attempt_id)
        self.assertEqual(attempt.status, ExamAttemptStatus.AUTO_SUBMITTED)
        self.assertIsNotNone(attempt.submitted_at)
        history_response = self.client.get(reverse('exam-history', kwargs={'pk': self.exam.id}))
        self.assertEqual(history_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(history_response.data), 1)

    def test_unpublished_exam_is_not_discoverable_or_startable(self):
        self.exam.published = False
        self.exam.save(update_fields=['published', 'updated_at'])
        response = self.client.post(reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_only_exam_manager_can_publish_a_new_schedule(self):
        self.client.force_authenticate(self.admin)
        create_response = self.client.post(
            reverse('exam-list'),
            {
                'institute': str(self.institute.id),
                'paper': str(self.paper.id),
                'batch': str(self.batch.id),
                'section': str(self.section.id),
                'starts_at': (timezone.now() + timedelta(hours=2)).isoformat(),
                'ends_at': (timezone.now() + timedelta(hours=3)).isoformat(),
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        new_exam_id = create_response.data['id']
        self.assertFalse(create_response.data['published'])

        self.client.force_authenticate(self.student)
        exams_response = self.client.get(reverse('exam-list'))
        student_exam_ids = {item['id'] for item in exams_response.data['results']}
        self.assertNotIn(new_exam_id, student_exam_ids)

        self.client.force_authenticate(self.admin)
        publish_response = self.client.post(
            reverse('exam-publish', kwargs={'pk': new_exam_id}), {}, format='json'
        )
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)
        self.assertTrue(publish_response.data['published'])
        repeated_publish = self.client.post(
            reverse('exam-publish', kwargs={'pk': new_exam_id}), {}, format='json'
        )
        self.assertEqual(repeated_publish.status_code, status.HTTP_400_BAD_REQUEST)

    def test_exam_manager_cancels_schedule_with_central_audit(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse('exam-cancel', kwargs={'pk': self.exam.pk}), {}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'cancelled')
        self.assertTrue(AuditEvent.objects.filter(
            action='exam.schedule.cancelled',
            resource_id=str(self.exam.pk),
            institute=self.institute,
            actor=self.admin,
        ).exists())
        repeated = self.client.post(
            reverse('exam-cancel', kwargs={'pk': self.exam.pk}), {}, format='json'
        )
        self.assertEqual(repeated.status_code, status.HTTP_400_BAD_REQUEST)

    def test_objective_answers_are_graded_once_and_results_are_attempt_scoped(self):
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        self.client.put(
            reverse('exam-attempt-answers', kwargs={'pk': attempt['id']}),
            {'question': str(self.question.id), 'response': 'A'},
            format='json',
        )
        submit_url = reverse('exam-attempt-submit', kwargs={'pk': attempt['id']})
        self.assertEqual(self.client.post(submit_url, {}, format='json').status_code, status.HTTP_200_OK)
        self.client.post(submit_url, {}, format='json')

        evaluation = ExamAnswerEvaluation.objects.get(
            answer__attempt_id=attempt['id'], answer__paper_question=self.question
        )
        self.assertEqual(evaluation.marks_awarded, Decimal('2.00'))
        self.assertEqual(ExamAnswerEvaluation.objects.filter(answer__attempt_id=attempt['id']).count(), 1)
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']}))
        self.assertEqual(result.status_code, status.HTTP_200_OK)
        self.assertEqual(result.data['marks_awarded'], '2.00')
        self.assertTrue(result.data['is_final'])
        self.assertNotIn('is_correct', result.data['questions'][0])

        other = User.objects.create_user(email='other-result@exam.edu', password='OtherPass123!')
        self.client.force_authenticate(other)
        self.assertEqual(
            self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']})).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_incorrect_objective_answer_uses_negative_marks_and_blank_is_zero(self):
        question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='B',
            section_order=2,
            question_number=2,
            question_version=1,
            question_type='mcq',
            question_text='Choose the correct answer.',
            marks=Decimal('2.00'),
            negative_marks=Decimal('0.50'),
            difficulty='easy',
            bloom_taxonomy='remember',
            options_snapshot=[
                {'option_key': 'A', 'option_text': 'Correct', 'is_correct': True},
                {'option_key': 'B', 'option_text': 'Incorrect', 'is_correct': False},
            ],
        )
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        self.client.put(
            reverse('exam-attempt-answers', kwargs={'pk': attempt['id']}),
            {'question': str(question.id), 'response': 'B'},
            format='json',
        )
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json'
        )
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']}))
        by_question = {item['question']: item for item in result.data['questions']}
        self.assertEqual(by_question[str(question.id)]['marks_awarded'], '-0.50')
        self.assertEqual(by_question[str(self.question.id)]['marks_awarded'], '0.00')
        self.assertTrue(result.data['is_final'])

    def test_missing_released_answer_key_requires_review_instead_of_awarding_wrong_marks(self):
        question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='B',
            section_order=2,
            question_number=2,
            question_version=1,
            question_type='mcq',
            question_text='Choose an option.',
            marks=Decimal('2.00'),
            negative_marks=Decimal('0.50'),
            difficulty='easy',
            bloom_taxonomy='remember',
            options_snapshot=[
                {'option_key': 'A', 'option_text': 'First'},
                {'option_key': 'B', 'option_text': 'Second'},
            ],
        )
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        self.client.put(
            reverse('exam-attempt-answers', kwargs={'pk': attempt['id']}),
            {'question': str(question.id), 'response': 'B'},
            format='json',
        )
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json'
        )
        evaluation = ExamAnswerEvaluation.objects.get(
            answer__attempt_id=attempt['id'], answer__paper_question=question
        )
        self.assertEqual(evaluation.status, 'human_review')
        self.assertIsNone(evaluation.marks_awarded)

    def test_coding_submissions_use_external_provider_and_do_not_return_test_details(self):
        coding_question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='B',
            section_order=2,
            question_number=2,
            question_version=1,
            question_type='coding',
            question_text='Return the input.',
            marks=Decimal('2.00'),
            difficulty='easy',
            bloom_taxonomy='apply',
            test_cases_snapshot=[
                {'input': 'public', 'expected_output': 'public', 'is_hidden': False},
                {'input': 'hidden-secret', 'expected_output': 'hidden-result', 'is_hidden': True},
            ],
            code_metadata_snapshot={
                'language': 'python',
                'supported_languages': ['python'],
                'execution_constraints': {'time_limit_seconds': 4, 'memory_limit_mb': 256},
            },
        )
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        questions = self.client.get(reverse('exam-questions', kwargs={'pk': self.exam.id}))
        coding_payload = next(item for item in questions.data if item['id'] == str(coding_question.id))
        self.assertNotIn('test_cases_snapshot', coding_payload)
        self.assertNotIn('hidden-secret', str(coding_payload))

        submission_url = reverse('exam-attempt-coding-submissions', kwargs={'pk': attempt['id']})
        payload = {'question': str(coding_question.id), 'code': 'print(input())', 'language': 'python'}
        first = self.client.post(submission_url, payload, format='json')
        duplicate = self.client.post(submission_url, payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(duplicate.data['id'], first.data['id'])
        self.assertNotIn('code', first.data)
        self.assertNotIn('passed_count', first.data)

        with patch('apps.exams.evaluation_services.CodeExecutionProvider.execute', return_value=[True, False]) as run:
            execute_url = reverse('coding-submission-execute', kwargs={'pk': first.data['id']})
            executed = self.client.post(execute_url, {}, format='json')
        self.assertEqual(executed.status_code, status.HTTP_200_OK)
        self.assertEqual(executed.data['status'], 'completed')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs['test_cases'][1]['input'], 'hidden-secret')
        self.assertEqual(
            ExamAnswerEvaluation.objects.get(answer__coding_submissions__id=first.data['id']).marks_awarded,
            Decimal('1.00'),
        )
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json'
        )
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']}))
        self.assertTrue(result.data['is_final'])

    def test_unsubmitted_coding_question_receives_zero_on_final_submission(self):
        coding_question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='B',
            section_order=2,
            question_number=2,
            question_version=1,
            question_type='coding',
            question_text='Return the input.',
            marks=Decimal('2.00'),
            difficulty='easy',
            bloom_taxonomy='apply',
            test_cases_snapshot=[{'input': 'x', 'expected_output': 'x'}],
            code_metadata_snapshot={'language': 'python'},
        )
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json'
        )
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']}))
        coding_result = next(
            item for item in result.data['questions'] if item['question'] == str(coding_question.id)
        )
        self.assertEqual(coding_result['marks_awarded'], '0.00')
        self.assertTrue(result.data['is_final'])
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json'
        )
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']}))
        self.assertTrue(result.data['is_final'])

    def test_unsubmitted_coding_question_receives_zero_on_final_submission(self):
        coding_question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='B',
            section_order=2,
            question_number=2,
            question_version=1,
            question_type='coding',
            question_text='Return the input.',
            marks=Decimal('2.00'),
            difficulty='easy',
            bloom_taxonomy='apply',
            test_cases_snapshot=[{'input': 'x', 'expected_output': 'x'}],
            code_metadata_snapshot={'language': 'python'},
        )
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json'
        )
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']}))
        coding_result = next(
            item for item in result.data['questions'] if item['question'] == str(coding_question.id)
        )
        self.assertEqual(coding_result['marks_awarded'], '0.00')
        self.assertTrue(result.data['is_final'])

    def test_coding_execution_fails_clearly_without_provider_configuration(self):
        coding_question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='B',
            section_order=2,
            question_number=2,
            question_version=1,
            question_type='coding',
            question_text='Return the input.',
            marks=Decimal('2.00'),
            difficulty='easy',
            bloom_taxonomy='apply',
            test_cases_snapshot=[{'input': 'x', 'expected_output': 'x'}],
            code_metadata_snapshot={'language': 'python'},
        )
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        submission = self.client.post(
            reverse('exam-attempt-coding-submissions', kwargs={'pk': attempt['id']}),
            {'question': str(coding_question.id), 'code': 'print(input())', 'language': 'python'},
            format='json',
        )
        with override_settings(CODE_EXECUTION_PROVIDER_URL='', CODE_EXECUTION_PROVIDER_TOKEN=''):
            response = self.client.post(
                reverse('coding-submission-execute', kwargs={'pk': submission.data['id']}),
                {},
                format='json',
            )
        self.assertEqual(response.status_code, 503)
        persisted = CodingSubmission.objects.get(pk=submission.data['id'])
        self.assertEqual(persisted.status, 'queued')
        self.assertEqual(persisted.error_code, 'provider_not_configured')
        self.client.post(
            reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json'
        )
        self.client.force_authenticate(self.admin)
        with patch('apps.exams.evaluation_services.CodeExecutionProvider.execute', return_value=[True]):
            completed = self.client.post(
                reverse('coding-submission-execute', kwargs={'pk': submission.data['id']}),
                {},
                format='json',
            )
        self.assertEqual(completed.status_code, status.HTTP_200_OK)
        result = self.client.get(reverse('exam-attempt-result', kwargs={'pk': attempt['id']}))
        self.assertEqual(result.data['marks_awarded'], '2.00')

    def test_handwritten_sheet_requires_manager_rubric_review(self):
        handwritten_question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='B',
            section_order=2,
            question_number=2,
            question_version=1,
            question_type='long_answer',
            question_text='Explain the concept.',
            marks=Decimal('2.00'),
            difficulty='medium',
            bloom_taxonomy='understand',
            rubric_snapshot=[{'criterion': 'Accuracy', 'description': 'Correctness', 'max_marks': '2.00'}],
        )
        attempt = self.client.post(
            reverse('exam-start', kwargs={'pk': self.exam.id}), {}, format='json'
        ).data
        self.client.post(reverse('exam-attempt-submit', kwargs={'pk': attempt['id']}), {}, format='json')
        media_dir = TemporaryDirectory()
        settings_override = override_settings(MEDIA_ROOT=media_dir.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.addCleanup(media_dir.cleanup)
        private_storage = HandwrittenAnswerSheet._meta.get_field('file').storage
        original_location = private_storage._location
        private_storage._location = f'{media_dir.name}\\private'
        self.addCleanup(setattr, private_storage, '_location', original_location)
        sheet = self.client.post(
            reverse('handwritten-answer-sheet-list'),
            {
                'attempt': attempt['id'],
                'file': SimpleUploadedFile('answers.pdf', b'%PDF-1.4 sample'),
            },
            format='multipart',
        )
        self.assertEqual(sheet.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(sheet.data['extracted_text'])
        self.client.force_authenticate(self.admin)
        with override_settings(OCR_PROVIDER_URL='', OCR_PROVIDER_TOKEN=''):
            extraction = self.client.post(
                reverse('handwritten-answer-sheet-extract', kwargs={'pk': sheet.data['id']}),
                {},
                format='json',
            )
        self.assertEqual(extraction.status_code, 503)
        self.client.force_authenticate(self.student)

        review_url = reverse('handwritten-answer-sheet-review', kwargs={'pk': sheet.data['id']})
        review_payload = {
            'evaluations': [{
                'question': str(handwritten_question.id),
                'marks_awarded': '1.00',
                'rubric_scores': {'Accuracy': '1.00'},
                'feedback': 'Partially correct.',
            }],
        }
        self.assertEqual(self.client.post(review_url, review_payload, format='json').status_code, 403)
        self.client.force_authenticate(self.admin)
        reviewed = self.client.post(review_url, review_payload, format='json')
        self.assertEqual(reviewed.status_code, status.HTTP_200_OK)
        self.assertEqual(reviewed.data['status'], 'reviewed')
        self.assertEqual(reviewed.data['evaluations'][0]['marks_awarded'], '1.00')
        self.assertEqual(reviewed.data['extracted_text'], '')
        download = self.client.get(
            reverse('handwritten-answer-sheet-download', kwargs={'pk': sheet.data['id']})
        )
        self.assertEqual(download.status_code, status.HTTP_200_OK)
        self.assertIn('no-store', download['Cache-Control'])
        download.close()

        other_student = User.objects.create_user(
            email='other-sheet@exam.edu', password='OtherPass123!', is_verified=True
        )
        self.client.force_authenticate(other_student)
        detail_url = reverse('handwritten-answer-sheet-detail', kwargs={'pk': sheet.data['id']})
        self.assertEqual(self.client.get(detail_url).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            self.client.get(
                reverse('handwritten-answer-sheet-download', kwargs={'pk': sheet.data['id']})
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
