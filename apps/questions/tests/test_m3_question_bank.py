from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import (
    User,
    Institute,
    UserInstituteMembership,
    RoleChoices,
    MembershipStatus,
)
from apps.academics.models import (
    Department,
    Program,
    Subject,
    Unit,
    Topic,
    LearningOutcome,
)
from apps.questions.models import (
    Question,
    QuestionOption,
    AnswerKey,
    QuestionRubric,
    QuestionSourceReference,
    QuestionVersion,
    QuestionTag,
    QuestionType,
    QuestionStatus,
    DifficultyLevel,
)


class M3QuestionBankManagementTests(APITestCase):

    def setUp(self):
        # 1. Platform Admin
        self.platform_admin = User.objects.create_superuser(
            email='super@examcraft.org',
            password='AdminPassword123!'
        )

        # 2. Institutes: Alpha & Beta
        self.institute_alpha = Institute.objects.create(code='ALPHA', name='Alpha Institute')
        self.institute_beta = Institute.objects.create(code='BETA', name='Beta Institute')

        # 3. Alpha Admin
        self.alpha_admin = User.objects.create_user(
            email='admin@alpha.edu',
            password='Password123!',
            first_name='Alpha',
            last_name='Admin',
            is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.alpha_admin,
            institute=self.institute_alpha,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE
        )

        # 4. Teacher in Alpha
        self.teacher_alpha = User.objects.create_user(
            email='teacher@alpha.edu',
            password='Password123!',
            first_name='Grace',
            last_name='Hopper',
            is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.teacher_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        # 5. Student in Alpha
        self.student_alpha = User.objects.create_user(
            email='student@alpha.edu',
            password='Password123!',
            first_name='Ada',
            last_name='Lovelace',
            is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.student_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.STUDENT,
            status=MembershipStatus.ACTIVE
        )

        # 5b. Second Teacher in Alpha
        self.teacher_2_alpha = User.objects.create_user(
            email='teacher2@alpha.edu',
            password='Password123!',
            first_name='Alan',
            last_name='Turing',
            is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.teacher_2_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.TEACHER,
            status=MembershipStatus.ACTIVE
        )

        # 5c. Exam Staff in Alpha
        self.exam_staff_alpha = User.objects.create_user(
            email='examstaff@alpha.edu',
            password='Password123!',
            first_name='Charles',
            last_name='Babbage',
            is_verified=True
        )
        UserInstituteMembership.objects.create(
            user=self.exam_staff_alpha,
            institute=self.institute_alpha,
            role=RoleChoices.EXAM_STAFF,
            status=MembershipStatus.ACTIVE,
            exam_permissions=['moderator']
        )

        # 6. Academic Hierarchy for Alpha
        self.dept_cs = Department.objects.create(institute=self.institute_alpha, code='CSE', name='Computer Science')
        self.prog_btech = Program.objects.create(institute=self.institute_alpha, department=self.dept_cs, code='BTECH', name='B.Tech')
        self.subj_dsa = Subject.objects.create(institute=self.institute_alpha, department=self.dept_cs, code='CS101', name='Data Structures')
        self.unit_trees = Unit.objects.create(subject=self.subj_dsa, unit_number=1, title='Binary Search Trees')
        self.topic_avl = Topic.objects.create(unit=self.unit_trees, title='AVL Trees and Balancing', order=1)
        self.lo_analyze = LearningOutcome.objects.create(
            subject=self.subj_dsa,
            code='CO1',
            description='Analyze time complexity of tree operations.',
            category='cognitive'
        )

        # 7. Academic Structure for Beta
        self.dept_beta = Department.objects.create(institute=self.institute_beta, code='BETA-CS', name='Beta CS')
        self.subj_beta = Subject.objects.create(institute=self.institute_beta, department=self.dept_beta, code='BETA101', name='Beta Physics')

        # 8. Tag in Alpha
        self.tag_algorithms = QuestionTag.objects.create(institute=self.institute_alpha, name='Algorithms')

    # --------------------------------------------------------------------------
    # Question Creation by Type Tests
    # --------------------------------------------------------------------------

    def test_create_mcq_question_with_normalized_options(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'unit': str(self.unit_trees.id),
            'topic': str(self.topic_avl.id),
            'learning_outcome': str(self.lo_analyze.id),
            'question_type': QuestionType.MCQ,
            'question_text': 'What is the worst-case lookup time in an AVL tree with n nodes?',
            'difficulty': DifficultyLevel.MEDIUM,
            'marks': '2.00',
            'negative_marks': '0.50',
            'bloom_taxonomy': 'understand',
            'options': [
                {'option_key': 'A', 'option_text': 'O(1)', 'is_correct': False},
                {'option_key': 'B', 'option_text': 'O(log n)', 'is_correct': True, 'explanation': 'AVL trees guarantee O(log n) height.'},
                {'option_key': 'C', 'option_text': 'O(n)', 'is_correct': False},
                {'option_key': 'D', 'option_text': 'O(n log n)', 'is_correct': False},
            ],
            'tag_ids': [str(self.tag_algorithms.id)]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], QuestionStatus.DRAFT)
        self.assertEqual(response.data['current_version'], 1)
        self.assertEqual(len(response.data['options']), 4)
        self.assertTrue(any(opt['is_correct'] for opt in response.data['options']))

    def test_create_true_false_question(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.TRUE_FALSE,
            'question_text': 'An AVL tree is a self-balancing binary search tree.',
            'marks': '1.00',
            'options': [
                {'option_key': 'A', 'option_text': 'True', 'is_correct': True},
                {'option_key': 'B', 'option_text': 'False', 'is_correct': False},
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['options']), 2)

    def test_create_short_and_long_answer_with_rubrics(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.LONG_ANSWER,
            'question_text': 'Explain the rebalancing mechanism of an AVL tree after insertion, with rotation diagrams.',
            'marks': '10.00',
            'answer_key': {
                'expected_answer': 'Detailed explanation of LL, RR, LR, and RL rotations with height balance factors.',
                'keywords': ['rotation', 'balance factor', 'LL rotation', 'RR rotation']
            },
            'rubrics': [
                {'criterion': 'Balance factor definition', 'description': 'Correctly defines height(left) - height(right)', 'max_marks': '2.00', 'order': 1},
                {'criterion': 'Single rotations', 'description': 'Explains LL and RR rotations with illustrations', 'max_marks': '4.00', 'order': 2},
                {'criterion': 'Double rotations', 'description': 'Explains LR and RL rotations with illustrations', 'max_marks': '4.00', 'order': 3},
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['rubrics']), 3)
        self.assertIsNotNone(response.data['answer_key'])

    def test_create_coding_question_with_test_cases(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.CODING,
            'question_text': 'Write a function `is_balanced(root)` that returns True if the given binary tree is height-balanced.',
            'marks': '15.00',
            'code_metadata': {
                'language': 'python',
                'starter_template': 'def is_balanced(root):\n    pass',
                'time_limit_ms': 1000,
                'memory_limit_mb': 256
            },
            'answer_key': {
                'expected_answer': 'Recursive post-order traversal calculating height and balance condition.',
                'test_cases': [
                    {'input': '[3,9,20,null,null,15,7]', 'expected_output': 'True', 'is_hidden': False},
                    {'input': '[1,2,2,3,3,null,null,4,4]', 'expected_output': 'False', 'is_hidden': True},
                ]
            }
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['question_type'], 'coding')
        self.assertEqual(len(response.data['answer_key']['test_cases']), 2)

    # --------------------------------------------------------------------------
    # Validation & Invariant Tests
    # --------------------------------------------------------------------------

    def test_reject_mcq_with_no_correct_option(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.MCQ,
            'question_text': 'Question with no correct answer?',
            'options': [
                {'option_key': 'A', 'option_text': 'Wrong 1', 'is_correct': False},
                {'option_key': 'B', 'option_text': 'Wrong 2', 'is_correct': False},
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('options', response.data['error']['details'])

    def test_reject_true_false_with_multiple_correct_options(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.TRUE_FALSE,
            'question_text': 'Invalid True/False with two true answers?',
            'options': [
                {'option_key': 'A', 'option_text': 'True', 'is_correct': True},
                {'option_key': 'B', 'option_text': 'False', 'is_correct': True},  # Both True!
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_negative_marks_greater_than_positive_marks(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.MCQ,
            'question_text': 'Excessive penalty question',
            'marks': '1.00',
            'negative_marks': '2.00',  # Greater than positive marks!
            'options': [
                {'option_key': 'A', 'option_text': 'Option 1', 'is_correct': True},
                {'option_key': 'B', 'option_text': 'Option 2', 'is_correct': False},
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_direct_approval_on_creation(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.MCQ,
            'question_text': 'Self-approving question attempt',
            'status': QuestionStatus.APPROVED,  # Must NOT be allowed!
            'options': [
                {'option_key': 'A', 'option_text': 'Option 1', 'is_correct': True},
                {'option_key': 'B', 'option_text': 'Option 2', 'is_correct': False},
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_cross_institute_subject(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')
        payload = {
            'institute': str(self.institute_alpha.id),  # Alpha
            'subject': str(self.subj_beta.id),         # Beta!
            'question_type': QuestionType.MCQ,
            'question_text': 'Cross institute question',
            'options': [
                {'option_key': 'A', 'option_text': '1', 'is_correct': True},
                {'option_key': 'B', 'option_text': '2', 'is_correct': False},
            ]
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --------------------------------------------------------------------------
    # Version History & Provenance Tests
    # --------------------------------------------------------------------------

    def test_question_update_creates_immutable_version_snapshot(self):
        # 1. Create initial question (Version 1)
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='Initial question text v1',
            marks=Decimal('2.00'),
            created_by=self.teacher_alpha,
            status=QuestionStatus.DRAFT
        )
        AnswerKey.objects.create(question=question, expected_answer='Initial solution v1')
        self.assertEqual(question.current_version, 1)

        # 2. Update question via API (Version 2)
        self.client.force_authenticate(user=self.teacher_alpha)
        update_url = reverse('question-detail', kwargs={'pk': question.id})
        response = self.client.patch(update_url, {
            'question_text': 'Updated refined question text v2',
            'marks': '4.00',
            'change_reason': 'Refined clarity and increased mark allocation'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify question updated
        question.refresh_from_db()
        self.assertEqual(question.question_text, 'Updated refined question text v2')
        self.assertEqual(question.marks, Decimal('4.00'))
        self.assertEqual(question.current_version, 2)

        # Verify historical snapshot of Version 1 exists and is preserved
        versions = question.versions.all()
        self.assertEqual(versions.count(), 1)
        v1 = versions.first()
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v1.snapshot_data['question_text'], 'Initial question text v1')
        self.assertEqual(v1.snapshot_data['marks'], '2.00')

        # 3. Verify versions action endpoint
        versions_url = reverse('question-versions', kwargs={'pk': question.id})
        v_resp = self.client.get(versions_url)
        self.assertEqual(v_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(v_resp.data), 1)

    def test_question_source_reference_provenance(self):
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='What is a red-black tree property?',
            marks=Decimal('2.00'),
            created_by=self.teacher_alpha
        )
        QuestionSourceReference.objects.create(
            question=question,
            source_title='Introduction to Algorithms (CLRS)',
            page_or_section='Chapter 13, Section 13.1, p. 308',
            excerpt='A red-black tree is a binary search tree with one extra bit of storage per node: its color...',
            relevance_note='Defines fundamental invariants of red-black trees'
        )

        self.client.force_authenticate(user=self.teacher_alpha)
        sources_url = reverse('question-source-references', kwargs={'pk': question.id})
        response = self.client.get(sources_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIn('CLRS', response.data[0]['source_title'])

    def test_submit_for_review_transition(self):
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='What is tree depth?',
            marks=Decimal('2.00'),
            status=QuestionStatus.DRAFT,
            created_by=self.teacher_alpha
        )
        self.client.force_authenticate(user=self.teacher_alpha)
        submit_url = reverse('question-submit-for-review', kwargs={'pk': question.id})
        response = self.client.post(submit_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        question.refresh_from_db()
        self.assertEqual(question.status, QuestionStatus.UNDER_REVIEW)

    # --------------------------------------------------------------------------
    # Permissions & Tenant Isolation Tests
    # --------------------------------------------------------------------------

    def test_student_cannot_create_or_view_question_bank(self):
        self.client.force_authenticate(user=self.student_alpha)
        url = reverse('question-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        post_resp = self.client.post(url, {
            'institute': str(self.institute_alpha.id),
            'subject': str(self.subj_dsa.id),
            'question_type': QuestionType.MCQ,
            'question_text': 'Student attempting to add question',
            'options': [
                {'option_key': 'A', 'option_text': '1', 'is_correct': True},
                {'option_key': 'B', 'option_text': '2', 'is_correct': False},
            ]
        })
        self.assertEqual(post_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_institute_question_access_blocked(self):
        """
        Question created in Beta must not be accessible to Teacher in Alpha.
        """
        q_beta = Question.objects.create(
            institute=self.institute_beta,
            subject=self.subj_beta,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='Beta confidential physics question',
            marks=Decimal('5.00')
        )

        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-detail', kwargs={'pk': q_beta.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_teacher_cannot_edit_another_teachers_question(self):
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='Teacher 1 private draft question',
            marks=Decimal('2.00'),
            created_by=self.teacher_alpha,
            status=QuestionStatus.DRAFT
        )
        self.client.force_authenticate(user=self.teacher_2_alpha)
        url = reverse('question-detail', kwargs={'pk': question.id})
        response = self.client.patch(url, {'question_text': 'Hacked by teacher 2'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_institute_admin_can_manage_institute_questions(self):
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='Teacher question managed by admin',
            marks=Decimal('3.00'),
            created_by=self.teacher_alpha,
            status=QuestionStatus.DRAFT
        )
        AnswerKey.objects.create(question=question, expected_answer='Valid answer for admin test')
        self.client.force_authenticate(user=self.alpha_admin)
        url = reverse('question-detail', kwargs={'pk': question.id})
        response = self.client.patch(url, {'question_text': 'Admin updated text'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        question.refresh_from_db()
        self.assertEqual(question.question_text, 'Admin updated text')

    def test_exam_staff_can_manage_institute_questions(self):
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='Teacher question reviewed by exam staff',
            marks=Decimal('4.00'),
            created_by=self.teacher_alpha,
            status=QuestionStatus.UNDER_REVIEW
        )
        self.client.force_authenticate(user=self.exam_staff_alpha)
        url = reverse('question-detail', kwargs={'pk': question.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_teacher_cannot_edit_approved_question(self):
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='Approved question',
            marks=Decimal('2.00'),
            created_by=self.teacher_alpha,
            status=QuestionStatus.APPROVED
        )
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-detail', kwargs={'pk': question.id})
        response = self.client.patch(url, {'question_text': 'Attempted modification'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_question_filtering_and_search(self):
        Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.MCQ,
            question_text='Algorithms Easy Question',
            difficulty=DifficultyLevel.EASY,
            marks=Decimal('1.00')
        )
        Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.LONG_ANSWER,
            question_text='Data Structures Hard Question',
            difficulty=DifficultyLevel.HARD,
            marks=Decimal('10.00')
        )
        self.client.force_authenticate(user=self.teacher_alpha)
        url = reverse('question-list')

        # Filter by difficulty
        resp_easy = self.client.get(url, {'difficulty': 'easy'})
        self.assertEqual(resp_easy.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_easy.data['count'], 1)
        self.assertEqual(resp_easy.data['results'][0]['question_type'], 'mcq')

        # Search by text
        resp_search = self.client.get(url, {'search': 'Algorithms'})
        self.assertEqual(resp_search.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_search.data['count'], 1)

    def test_question_tag_and_review_endpoints(self):
        self.client.force_authenticate(user=self.teacher_alpha)
        tag_url = reverse('question-tag-list')
        tag_resp = self.client.post(tag_url, {
            'institute': str(self.institute_alpha.id),
            'name': 'Dynamic Programming'
        }, format='json')
        self.assertEqual(tag_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(tag_resp.data['slug'], 'dynamic-programming')

        # Question Review
        question = Question.objects.create(
            institute=self.institute_alpha,
            subject=self.subj_dsa,
            question_type=QuestionType.SHORT_ANSWER,
            question_text='Review target question',
            marks=Decimal('2.00'),
            status=QuestionStatus.UNDER_REVIEW
        )
        self.client.force_authenticate(user=self.exam_staff_alpha)
        review_url = reverse('question-review-list')
        review_resp = self.client.post(review_url, {
            'question': str(question.id),
            'decision': 'approved',
            'comment': 'Meets curriculum quality standards.'
        }, format='json')
        self.assertEqual(review_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(review_resp.data['decision'], 'approved')

