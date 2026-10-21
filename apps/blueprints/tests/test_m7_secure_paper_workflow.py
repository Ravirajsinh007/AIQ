from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import Institute, RoleChoices, User, UserInstituteMembership
from apps.academics.models import Department, Subject
from apps.audit.models import AuditEvent
from apps.blueprints.models import (
    BlueprintStatus,
    GeneratedPaper,
    GeneratedPaperQuestion,
    GeneratedPaperStatus,
    PaperBlueprint,
    PaperWorkflowStatus,
)
from apps.blueprints.workflow import (
    create_paper_amendment,
    release_paper,
    review_paper,
    schedule_paper_release,
    submit_paper_for_review,
)


class SecurePaperWorkflowTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(code='M7-TEST', name='M7 Test Institute')
        self.department = Department.objects.create(
            institute=self.institute, code='CS', name='Computer Science'
        )
        self.subject = Subject.objects.create(
            institute=self.institute,
            department=self.department,
            code='CS-101',
            name='Foundations',
        )
        self.blueprint = PaperBlueprint.objects.create(
            institute=self.institute,
            title='Foundations Blueprint',
            subject=self.subject,
            total_marks=Decimal('2.00'),
            duration_minutes=60,
            status=BlueprintStatus.ACTIVE,
        )
        self.creator = self._member('creator@m7.test', RoleChoices.INSTITUTE_ADMIN)
        self.approver = self._member('approver@m7.test', RoleChoices.INSTITUTE_ADMIN)
        self.paper = GeneratedPaper.objects.create(
            institute=self.institute,
            blueprint=self.blueprint,
            title='Foundations Paper v1',
            subject=self.subject,
            total_marks=Decimal('2.00'),
            duration_minutes=60,
            status=GeneratedPaperStatus.COMPLETED,
            created_by=self.creator,
        )
        self.question = GeneratedPaperQuestion.objects.create(
            paper=self.paper,
            section_name='A',
            section_order=1,
            question_number=1,
            question_version=1,
            question_type='mcq',
            question_text='Original immutable question',
            marks=Decimal('2.00'),
            difficulty='easy',
            bloom_taxonomy='remember',
            options_snapshot=[{'option_key': 'A', 'option_text': 'Option'}],
        )

    def _member(self, email, role):
        user = User.objects.create_user(email=email, password='TempPass123!')
        UserInstituteMembership.objects.create(
            user=user,
            institute=self.institute,
            role=role,
        )
        return user

    def test_creator_cannot_review_and_release_is_idempotent(self):
        submit_question = submit_paper_for_review(self.paper.pk, self.creator)
        self.assertEqual(submit_question.workflow_status, PaperWorkflowStatus.SUBMITTED)
        with self.assertRaises(PermissionDenied):
            review_paper(self.paper.pk, self.creator, approve=True)

        approved = review_paper(self.paper.pk, self.approver, approve=True)
        self.assertEqual(approved.workflow_status, PaperWorkflowStatus.APPROVED)
        release_at = timezone.now() + timedelta(seconds=1)
        scheduled = schedule_paper_release(self.paper.pk, self.approver, release_at)
        self.assertEqual(scheduled.workflow_status, PaperWorkflowStatus.SCHEDULED)

        released = release_paper(self.paper.pk, user=self.approver, at=release_at)
        repeated = release_paper(self.paper.pk, user=self.approver, at=release_at)
        self.assertEqual(released.workflow_status, PaperWorkflowStatus.RELEASED)
        self.assertEqual(repeated.released_at, released.released_at)
        self.assertEqual(
            AuditEvent.objects.filter(action='paper.released', resource_id=str(self.paper.pk)).count(),
            1,
        )

    def test_amendment_creates_new_version_without_mutating_original_snapshot(self):
        submit_paper_for_review(self.paper.pk, self.creator)
        review_paper(self.paper.pk, self.approver, approve=True)
        schedule_paper_release(
            self.paper.pk,
            self.approver,
            timezone.now() + timedelta(seconds=1),
        )
        release_paper(
            self.paper.pk,
            user=self.approver,
            at=timezone.now() + timedelta(seconds=2),
        )

        amended = create_paper_amendment(
            self.paper.pk,
            self.approver,
            title='Foundations Paper v2',
            reason='Correct a question wording issue.',
            question_edits=[{
                'question_number': 1,
                'question_text': 'Amended question text',
            }],
        )
        self.question.refresh_from_db()
        amended_question = amended.paper_questions.get(question_number=1)
        self.assertEqual(amended.workflow_status, PaperWorkflowStatus.DRAFT)
        self.assertEqual(amended.supersedes_id, self.paper.pk)
        self.assertEqual(self.question.question_text, 'Original immutable question')
        self.assertEqual(amended_question.question_text, 'Amended question text')
        self.assertGreater(amended.generation_version, self.paper.generation_version)

    def test_snapshot_rows_cannot_be_updated(self):
        self.question.question_text = 'Attempted in-place change'
        with self.assertRaises(DjangoValidationError):
            self.question.save()
