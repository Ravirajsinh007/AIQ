from decimal import Decimal
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    User,
    Institute,
    RoleChoices,
    UserInstituteMembership,
    MembershipStatus,
)
from apps.academics.models import (
    Department,
    Program,
    Subject,
)
from apps.questions.models import (
    Question,
    QuestionOption,
    AnswerKey,
    QuestionRubric,
    QuestionSourceReference,
    QuestionType,
    QuestionStatus,
    DifficultyLevel,
    BloomTaxonomy,
    QuestionOrigin,
)
from apps.reviews.models import QuestionReviewRecord, ReviewDecision


@pytest.mark.django_db
class M5QuestionReviewWorkflowTests(APITestCase):
    """
    Test suite for Module M5: Question Verification & Review.
    Validates:
    - Multi-tenant institute boundary isolation.
    - Role-based permissions (Admins, Reviewers, Teachers, Students).
    - Strict state transitions (draft/rejected -> under_review -> approved/rejected/draft).
    - Anti-self-approval enforcement (teachers cannot approve their own questions).
    - Rejection requires mandatory reason.
    - Revision request returns question to draft with feedback so author can update.
    - Archiving rules (Admins/Exam staff only, cannot archive under_review questions).
    - Inspection endpoint returns comprehensive details and full history.
    - Read-only review audit log tracking every decision and snapshot version.
    """

    def setUp(self):
        # 1. Institutes
        self.institute_alpha = Institute.objects.create(code='INST-ALPHA', name='Alpha Engineering Institute')
        self.institute_beta = Institute.objects.create(code='INST-BETA', name='Beta Polytechnic Institute')

        # 2. Users
        self.admin_alpha = User.objects.create_user(
            email='admin@alpha.edu',
            password='Password123!',
            first_name='Admin',
            last_name='Alpha',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.admin_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        self.teacher_author_alpha = User.objects.create_user(
            email='author@alpha.edu',
            password='Password123!',
            first_name='Author',
            last_name='Teacher',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.teacher_author_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        self.teacher_reviewer_alpha = User.objects.create_user(
            email='reviewer@alpha.edu',
            password='Password123!',
            first_name='Reviewer',
            last_name='Teacher',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.teacher_reviewer_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        self.exam_staff_alpha = User.objects.create_user(
            email='examstaff@alpha.edu',
            password='Password123!',
            first_name='Exam',
            last_name='Staff',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.exam_staff_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.EXAM_STAFF,
            status=MembershipStatus.ACTIVE
        )

        self.student_alpha = User.objects.create_user(
            email='student@alpha.edu',
            password='Password123!',
            first_name='Student',
            last_name='Learner',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.student_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE
        )

        # Cross-institute user
        self.admin_beta = User.objects.create_user(
            email='admin@beta.edu',
            password='Password123!',
            first_name='Admin',
            last_name='Beta',
            is_active=True,
            must_change_password=False
        )
        UserInstituteMembership.objects.create(
            user=self.admin_beta,
            institute=self.institute_beta,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        # Platform Admin
        self.platform_admin = User.objects.create_superuser(
            email='super@examcraft.io',
            password='Password123!',
            first_name='Super',
            last_name='Admin'
        )
        self.platform_admin.must_change_password = False
        self.platform_admin.save()

        # Academic context
        self.dept_alpha = Department.objects.create(
            institute=self.institute_alpha,
            code='CS',
            name='Computer Science'
        )
        self.prog_alpha = Program.objects.create(
            institute=self.institute_alpha,
            department=self.dept_alpha,
            code='CS-BTECH',
            name='B.Tech CSE'
        )
        self.subj_dsa = Subject.objects.create(
            institute=self.institute_alpha,
            department=self.dept_alpha,
            code='CS201',
            name='Data Structures & Algorithms'
        )

    def _create_mcq_question(self, author=None, status=QuestionStatus.DRAFT, origin=QuestionOrigin.MANUAL):
        author = author or self.teacher_author_alpha
        q = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.MCQ,
            question_text='What is the worst-case time complexity of QuickSort?',
            difficulty=DifficultyLevel.MEDIUM,
            marks=Decimal('2.00'),
            negative_marks=Decimal('0.50'),
            bloom_taxonomy=BloomTaxonomy.ANALYZE,
            origin_type=origin,
            status=status,
            current_version=1,
            created_by=author
        )
        QuestionOption.objects.create(question=q, option_key='A', option_text='O(n)', is_correct=False, order=1)
        QuestionOption.objects.create(question=q, option_key='B', option_text='O(n log n)', is_correct=False, order=2)
        QuestionOption.objects.create(question=q, option_key='C', option_text='O(n^2)', is_correct=True, order=3)
        QuestionOption.objects.create(question=q, option_key='D', option_text='O(1)', is_correct=False, order=4)
        QuestionSourceReference.objects.create(
            question=q,
            source_title='Introduction to Algorithms (CLRS)',
            page_or_section='Chapter 7, Page 174',
            excerpt='The worst-case running time of quicksort is Theta(n^2).'
        )
        return q

    # -------------------------------------------------------------------------
    # 1. Submission for Review Workflow
    # -------------------------------------------------------------------------
    def test_author_can_submit_draft_question_for_review(self):
        question = self._create_mcq_question(status=QuestionStatus.DRAFT)
        self.client.force_authenticate(user=self.teacher_author_alpha)

        url = reverse('review-workflow-submit-for-review', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'Ready for review by department.'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.UNDER_REVIEW)

        # Audit record created
        record = QuestionReviewRecord.objects.filter(question=question).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.to_status, QuestionStatus.UNDER_REVIEW)
        self.assertEqual(record.reviewer, self.teacher_author_alpha)

    def test_teacher_cannot_submit_another_teachers_draft_question(self):
        question = self._create_mcq_question(author=self.teacher_author_alpha, status=QuestionStatus.DRAFT)
        # Attempt submission by different teacher
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        url = reverse('review-workflow-submit-for-review', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'Unauthorized submission attempt.'})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.DRAFT)

    def test_cannot_submit_already_approved_or_under_review_question(self):
        question = self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_author_alpha)

        url = reverse('review-workflow-submit-for-review', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'Submitting duplicate review'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Cannot submit question for review from', response.data['error']['message'])

    # -------------------------------------------------------------------------
    # 2. Strict Anti-Self-Approval
    # -------------------------------------------------------------------------
    def test_anti_self_approval_blocks_author_from_approving_own_question(self):
        question = self._create_mcq_question(author=self.teacher_author_alpha, status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_author_alpha)

        url = reverse('review-workflow-approve', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'I approve my own question.'})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Authors cannot approve their own questions', response.data['error']['message'])
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.UNDER_REVIEW)

    # -------------------------------------------------------------------------
    # 3. Successful Approval by Authorized Peer Reviewer or Admin
    # -------------------------------------------------------------------------
    def test_peer_teacher_reviewer_can_approve_valid_question(self):
        question = self._create_mcq_question(author=self.teacher_author_alpha, status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        url = reverse('review-workflow-approve', kwargs={'pk': question.id})
        payload = {
            'notes': 'Verified algorithm analysis, options, and distractors are scientifically sound.',
            'rubric_scores': {'clarity': 5, 'accuracy': 5}
        }
        response = self.client.post(url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.APPROVED)

        # Audit review record verified
        record = QuestionReviewRecord.objects.filter(question=question, decision=ReviewDecision.APPROVE).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.reviewer, self.teacher_reviewer_alpha)
        self.assertEqual(record.from_status, QuestionStatus.UNDER_REVIEW)
        self.assertEqual(record.to_status, QuestionStatus.APPROVED)
        self.assertEqual(record.question_version, 1)

    def test_institute_admin_can_approve_question(self):
        question = self._create_mcq_question(author=self.teacher_author_alpha, status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.admin_alpha)

        url = reverse('review-workflow-approve', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'Approved by Institute Administrator.'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.APPROVED)

    def test_cannot_approve_question_not_under_review(self):
        question = self._create_mcq_question(status=QuestionStatus.DRAFT)
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        url = reverse('review-workflow-approve', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'Approving a draft directly.'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Question must be in 'under_review'", response.data['error']['message'])

    # -------------------------------------------------------------------------
    # 4. Rejection Workflow with Required Reason
    # -------------------------------------------------------------------------
    def test_rejection_requires_mandatory_rejection_reason(self):
        question = self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        url = reverse('review-workflow-reject', kwargs={'pk': question.id})
        # Empty payload without rejection_reason
        response = self.client.post(url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_details = response.data['error']['details']
        self.assertIn('rejection_reason', error_details)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.UNDER_REVIEW)

    def test_successful_rejection_records_audit_trail(self):
        question = self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        url = reverse('review-workflow-reject', kwargs={'pk': question.id})
        response = self.client.post(url, {
            'rejection_reason': 'Question text is ambiguous regarding worst-case pivot selection.'
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.REJECTED)

        record = QuestionReviewRecord.objects.filter(question=question, decision=ReviewDecision.REJECT).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.rejection_reason, 'Question text is ambiguous regarding worst-case pivot selection.')

    # -------------------------------------------------------------------------
    # 5. Request Revision & Author Resubmission Cycle
    # -------------------------------------------------------------------------
    def test_request_revision_returns_question_to_draft_for_author_editing(self):
        question = self._create_mcq_question(author=self.teacher_author_alpha, status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        url = reverse('review-workflow-request-revision', kwargs={'pk': question.id})
        response = self.client.post(url, {
            'revision_feedback': 'Please add explanations for each MCQ distractor option.'
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.DRAFT)

        # Now author edits the question (incrementing version snapshot)
        self.client.force_authenticate(user=self.teacher_author_alpha)
        update_url = reverse('question-detail', kwargs={'pk': question.id})
        patch_resp = self.client.patch(update_url, {
            'question_text': 'What is the worst-case runtime of QuickSort with standard deterministic pivot?',
            'change_reason': 'Clarified pivot selection as requested by reviewer.'
        })
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.current_version, 2)

        # Author resubmits revised question
        resubmit_url = reverse('review-workflow-submit-for-review', kwargs={'pk': question.id})
        resubmit_resp = self.client.post(resubmit_url, {'notes': 'Addressed feedback, updated version 2.'})
        self.assertEqual(resubmit_resp.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.UNDER_REVIEW)

        # Reviewer approves version 2
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)
        approve_url = reverse('review-workflow-approve', kwargs={'pk': question.id})
        app_resp = self.client.post(approve_url, {'notes': 'Version 2 looks excellent.'})
        self.assertEqual(app_resp.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.APPROVED)

    # -------------------------------------------------------------------------
    # 6. Multi-Tenant Boundary Isolation
    # -------------------------------------------------------------------------
    def test_cross_institute_reviewer_cannot_access_or_review_question(self):
        question = self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        # Authenticate as Beta Admin
        self.client.force_authenticate(user=self.admin_beta)

        url = reverse('review-workflow-approve', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'Cross-institute approval attempt'})

        # 404 due to tenant queryset isolation
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------------------
    # 7. Student Authorization Block
    # -------------------------------------------------------------------------
    def test_student_cannot_access_review_workflow_or_pending_queue(self):
        self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.student_alpha)

        pending_url = reverse('review-workflow-pending-reviews')
        response = self.client.get(pending_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 8. Platform Admin Cannot Approve for Institutes
    # -------------------------------------------------------------------------
    def test_platform_admin_cannot_approve_questions_on_behalf_of_institutes(self):
        question = self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.platform_admin)

        url = reverse('review-workflow-approve', kwargs={'pk': question.id})
        response = self.client.post(url, {'notes': 'Platform admin approval'})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 9. Inspection and Audit Log Endpoints
    # -------------------------------------------------------------------------
    def test_review_inspection_endpoint_returns_complete_package(self):
        question = self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        inspection_url = reverse('review-workflow-inspection', kwargs={'pk': question.id})
        response = self.client.get(inspection_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn('question', data)
        self.assertIn('review_history', data)
        self.assertEqual(data['question']['question_text'], question.question_text)
        self.assertEqual(len(data['question']['options']), 4)
        self.assertEqual(len(data['question']['source_references']), 1)

    def test_audit_log_endpoint_records_and_filters_decisions(self):
        question = self._create_mcq_question(status=QuestionStatus.UNDER_REVIEW)
        self.client.force_authenticate(user=self.teacher_reviewer_alpha)

        # Reject question
        reject_url = reverse('review-workflow-reject', kwargs={'pk': question.id})
        self.client.post(reject_url, {'rejection_reason': 'Flawed options'})

        # Query audit log
        audit_url = reverse('review-audit-log-list')
        response = self.client.get(audit_url, {'decision': ReviewDecision.REJECT})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]['decision'], ReviewDecision.REJECT)
        self.assertEqual(results[0]['rejection_reason'], 'Flawed options')

    # -------------------------------------------------------------------------
    # 10. Archiving Workflow
    # -------------------------------------------------------------------------
    def test_archiving_workflow_rules(self):
        question = self._create_mcq_question(status=QuestionStatus.APPROVED)

        # Teacher cannot archive
        self.client.force_authenticate(user=self.teacher_author_alpha)
        archive_url = reverse('review-workflow-archive', kwargs={'pk': question.id})
        teacher_resp = self.client.post(archive_url, {'reason': 'Old syllabus'})
        self.assertEqual(teacher_resp.status_code, status.HTTP_403_FORBIDDEN)

        # Exam staff can archive
        self.client.force_authenticate(user=self.exam_staff_alpha)
        staff_resp = self.client.post(archive_url, {'reason': 'Superseded by 2026 syllabus'})
        self.assertEqual(staff_resp.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.ARCHIVED)
