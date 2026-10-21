from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    Institute,
    MembershipStatus,
    RoleChoices,
    User,
    UserInstituteMembership,
)
from apps.notifications.models import EmailDeliveryStatus, Notification


class NotificationWorkflowTests(APITestCase):
    def setUp(self):
        self.institute = Institute.objects.create(code='NOT', name='Notifications Institute')
        self.admin = User.objects.create_user(
            email='admin@not.edu', password='AdminPass123!'
        )
        UserInstituteMembership.objects.create(
            user=self.admin, institute=self.institute,
            role=RoleChoices.INSTITUTE_ADMIN, status=MembershipStatus.ACTIVE,
        )
        self.student = User.objects.create_user(
            email='student@not.edu', password='StudentPass123!'
        )
        UserInstituteMembership.objects.create(
            user=self.student, institute=self.institute,
            role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE,
        )

    def test_notification_is_private_idempotent_and_readable(self):
        self.client.force_authenticate(self.admin)
        payload = {
            'institute': str(self.institute.pk),
            'recipient': str(self.student.pk),
            'subject': 'Exam update',
            'message': 'The schedule has been updated.',
            'event_key': 'exam-update-1',
        }
        first = self.client.post(reverse('notification-list'), payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(first.data['email_status'], EmailDeliveryStatus.NOT_CONFIGURED)
        duplicate = self.client.post(reverse('notification-list'), payload, format='json')
        self.assertEqual(duplicate.status_code, status.HTTP_200_OK)
        self.assertEqual(Notification.objects.count(), 1)

        notification_id = first.data['id']
        self.client.force_authenticate(self.student)
        own = self.client.get(reverse('notification-detail', kwargs={'pk': notification_id}))
        self.assertEqual(own.status_code, status.HTTP_200_OK)
        read = self.client.post(
            reverse('notification-mark-read', kwargs={'pk': notification_id}), {}, format='json'
        )
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(read.data['read_at'])

        outsider = User.objects.create_user(
            email='outsider@not.edu', password='OtherPass123!'
        )
        self.client.force_authenticate(outsider)
        hidden = self.client.get(reverse('notification-detail', kwargs={'pk': notification_id}))
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)

    def test_notification_sender_cannot_target_another_institute_member(self):
        other_institute = Institute.objects.create(code='OTHER', name='Other Institute')
        other_user = User.objects.create_user(
            email='other@not.edu', password='OtherPass123!'
        )
        UserInstituteMembership.objects.create(
            user=other_user, institute=other_institute,
            role=RoleChoices.STUDENT, status=MembershipStatus.ACTIVE,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse('notification-list'),
            {
                'institute': str(self.institute.pk),
                'recipient': str(other_user.pk),
                'subject': 'Cross-tenant',
                'message': 'Should not be sent.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Notification.objects.count(), 0)

    def test_smtp_delivery_status_is_sent_only_when_backend_confirms(self):
        from django.core import mail
        from django.test import override_settings

        self.client.force_authenticate(self.admin)
        with override_settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
            EMAIL_HOST='smtp.example.test',
            DEFAULT_FROM_EMAIL='noreply@example.test',
        ):
            response = self.client.post(
                reverse('notification-list'),
                {
                    'institute': str(self.institute.pk),
                    'recipient': str(self.student.pk),
                    'subject': 'Confirmed',
                    'message': 'Delivery is confirmed by the test backend.',
                },
                format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['email_status'], EmailDeliveryStatus.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_messages_without_event_keys_are_not_accidentally_deduplicated(self):
        self.client.force_authenticate(self.admin)
        for subject in ('First message', 'Second message'):
            response = self.client.post(
                reverse('notification-list'),
                {
                    'institute': str(self.institute.pk),
                    'recipient': str(self.student.pk),
                    'subject': subject,
                    'message': 'Distinct manual communication.',
                },
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Notification.objects.count(), 2)
